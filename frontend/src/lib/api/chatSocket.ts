import { ApiError, API_BASE_URL } from './client';
import { ChatResponseSchema, type ChatResponse } from './schemas';
import { sendChatMessage } from './queries';

/** Steps the server reports while it works on a question. */
export type ChatStage = 'retrieving' | 'writing_query' | 'running_query' | 'answering';

export interface ChatListener {
  onStage?: (stage: ChatStage) => void;
  /** A piece of the answer text, in order; the final result replaces whatever these built up. */
  onDelta?: (text: string) => void;
}

interface Pending extends ChatListener {
  resolve: (response: ChatResponse) => void;
  reject: (error: unknown) => void;
}

/** `ws(s)://…/api/chat/ws`; like every request it names no dataset, so the server's default is used. */
const socketUrl = () => `${API_BASE_URL.replace(/\/$/, '').replace(/^http/, 'ws')}/chat/ws`;

let counter = 0;

/**
 * One long-lived WebSocket to `/api/chat/ws`. Questions go out as `ask` frames and come back as
 * `status` / `delta` frames and a final `result`. It is opened by the first question and then kept
 * for the whole page session, one connection for every question: a heartbeat detects a dead link
 * (proxies drop idle sockets), and an unexpected close is followed by reconnects with backoff,
 * so the next question finds the socket already open. It is never closed between questions.
 * When the socket cannot be opened at all the question falls back to `POST /api/chat/messages`.
 */
const HEARTBEAT_MS = 25_000;
const PONG_TIMEOUT_MS = 10_000;
const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;
const MAX_FAILED_RECONNECTS = 6;

class ChatSocket {
  private socket: WebSocket | null = null;
  private opening: Promise<WebSocket> | null = null;
  private pending = new Map<string, Pending>();
  /** True once a question was asked: from then on the connection is maintained. */
  private keepOpen = false;
  private failedAttempts = 0;
  private heartbeat: ReturnType<typeof setInterval> | null = null;
  private pongTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    // Coming back online or to the tab is the best moment to repair a connection that dropped.
    if (typeof window !== 'undefined') {
      window.addEventListener('online', () => this.revive());
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') this.revive();
      });
    }
  }

  private revive() {
    if (!this.keepOpen || this.socket || this.opening) return;
    this.failedAttempts = 0;
    this.open().catch(() => undefined);
  }

  private startHeartbeat(socket: WebSocket) {
    this.stopHeartbeat();
    this.heartbeat = setInterval(() => {
      if (socket.readyState !== WebSocket.OPEN) return;
      socket.send(JSON.stringify({ type: 'ping' }));
      this.pongTimer ??= setTimeout(() => socket.close(), PONG_TIMEOUT_MS); // no pong: the link is dead
    }, HEARTBEAT_MS);
  }

  private stopHeartbeat() {
    if (this.heartbeat) clearInterval(this.heartbeat);
    if (this.pongTimer) clearTimeout(this.pongTimer);
    this.heartbeat = this.pongTimer = null;
  }

  private scheduleReconnect() {
    if (!this.keepOpen || this.reconnectTimer || this.failedAttempts >= MAX_FAILED_RECONNECTS) return;
    const delay = Math.min(RECONNECT_BASE_MS * 2 ** this.failedAttempts, RECONNECT_MAX_MS);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.socket || this.opening) return;
      this.open().catch(() => undefined); // a failure closes the socket, which schedules the next try
    }, delay);
  }

  private open(): Promise<WebSocket> {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) return Promise.resolve(this.socket);
    if (this.opening) return this.opening;
    this.opening = new Promise<WebSocket>((resolve, reject) => {
      const socket = new WebSocket(socketUrl());
      socket.onopen = () => {
        this.socket = socket;
        this.opening = null;
        this.failedAttempts = 0;
        this.startHeartbeat(socket);
        resolve(socket);
      };
      socket.onerror = () => {
        if (this.opening) {
          this.opening = null;
          reject(new ApiError('Could not open the chat connection.', 0));
        }
      };
      socket.onmessage = (event) => this.handle(event.data);
      socket.onclose = () => {
        if (this.socket === socket) this.socket = null;
        this.opening = null;
        this.stopHeartbeat();
        this.failedAttempts += 1;
        this.scheduleReconnect();
        const dropped = new ApiError('The chat connection was lost.', 0);
        for (const [id, entry] of this.pending) {
          this.pending.delete(id);
          entry.reject(dropped);
        }
      };
    });
    return this.opening;
  }

  private handle(raw: unknown) {
    let frame: { type?: string; id?: string; stage?: ChatStage; text?: string; result?: unknown; retry_after?: number; code?: string; detail?: string };
    try {
      frame = JSON.parse(String(raw));
    } catch {
      return;
    }
    if (frame.type === 'pong') {
      if (this.pongTimer) clearTimeout(this.pongTimer);
      this.pongTimer = null;
      return;
    }
    const entry = frame.id ? this.pending.get(frame.id) : undefined;
    if (!entry || !frame.id) return;
    if (frame.type === 'status' && frame.stage) entry.onStage?.(frame.stage);
    else if (frame.type === 'delta' && frame.text) entry.onDelta?.(frame.text);
    else if (frame.type === 'result') {
      this.pending.delete(frame.id);
      const parsed = ChatResponseSchema.safeParse(frame.result);
      if (!parsed.success) entry.reject(new ApiError('The server sent an unreadable answer.', 502));
      else if (parsed.data.error === 'rate_limited') {
        entry.reject(new ApiError('Too many questions.', 429, { detail: parsed.data.answer, retryAfter: frame.retry_after }));
      } else entry.resolve(parsed.data);
    } else if (frame.type === 'error' || frame.type === 'cancelled') {
      this.pending.delete(frame.id);
      entry.reject(new ApiError(frame.detail ?? 'The question was not answered.', 500, { code: frame.code, detail: frame.detail }));
    }
  }

  async ask(message: string, listener: ChatListener = {}): Promise<ChatResponse> {
    let socket: WebSocket;
    if (!this.keepOpen) this.keepOpen = true; // the first question starts the session's connection
    this.failedAttempts = 0;
    try {
      socket = await this.open();
    } catch {
      return sendChatMessage(message); // sockets blocked (proxy, old server): plain request
    }
    const id = `q-${Date.now()}-${(counter += 1)}`;
    return new Promise<ChatResponse>((resolve, reject) => {
      this.pending.set(id, { ...listener, resolve, reject });
      try {
        socket.send(JSON.stringify({ type: 'ask', id, message }));
      } catch (error) {
        this.pending.delete(id);
        reject(error);
      }
    });
  }
}

export const chatSocket = new ChatSocket();
