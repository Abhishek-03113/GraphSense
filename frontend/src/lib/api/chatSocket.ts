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
 * `status` / `delta` frames and a final `result`. Opened on first use and reopened after a drop.
 * When the socket cannot be opened at all the question falls back to `POST /api/chat/messages`.
 */
class ChatSocket {
  private socket: WebSocket | null = null;
  private opening: Promise<WebSocket> | null = null;
  private pending = new Map<string, Pending>();

  private open(): Promise<WebSocket> {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) return Promise.resolve(this.socket);
    if (this.opening) return this.opening;
    this.opening = new Promise<WebSocket>((resolve, reject) => {
      const socket = new WebSocket(socketUrl());
      socket.onopen = () => {
        this.socket = socket;
        this.opening = null;
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
