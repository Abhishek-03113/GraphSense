import type { z } from 'zod';

/** Base URL of the GraphSense API, including the `/api` prefix. Override with VITE_API_BASE_URL. */
export const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL as string | undefined) || 'http://localhost:8000/api';

export interface ApiErrorInfo {
  detail?: string;
  /** Stable machine code from the error envelope, e.g. "dataset_not_ready". */
  code?: string;
  requestId?: string;
  /** Seconds to wait before trying again, from a `Retry-After` header. */
  retryAfter?: number;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail?: string;
  readonly code?: string;
  readonly requestId?: string;
  readonly retryAfter?: number;

  constructor(message: string, status: number, info: ApiErrorInfo | string = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    const details: ApiErrorInfo = typeof info === 'string' ? { detail: info } : info;
    this.detail = details.detail;
    this.code = details.code;
    this.requestId = details.requestId;
    this.retryAfter = details.retryAfter;
  }

  /** True when the server could not be reached at all. */
  get isNetwork(): boolean {
    return this.status === 0;
  }

  /** True when the dataset exists but its data has not been loaded (yet). */
  get isDatasetNotReady(): boolean {
    return this.code === 'dataset_not_ready';
  }
}

/** True for the "dataset data is not loaded yet" answer (409 `dataset_not_ready`). */
export const isDatasetNotReady = (error: unknown): boolean => error instanceof ApiError && error.isDatasetNotReady;

type Params = Record<string, string | number | boolean | null | undefined>;

function buildUrl(path: string, params?: Params): string {
  const url = `${API_BASE_URL.replace(/\/$/, '')}${path}`;
  if (!params) return url;
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value));
  }
  const text = query.toString();
  return text ? `${url}?${text}` : url;
}

/** Seconds from a `Retry-After` header given as a number of seconds or an HTTP date. */
function parseRetryAfter(value: string | null): number | undefined {
  if (!value) return undefined;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.ceil(seconds);
  const when = Date.parse(value);
  return Number.isNaN(when) ? undefined : Math.max(0, Math.ceil((when - Date.now()) / 1000));
}

async function readError(response: Response): Promise<ApiErrorInfo> {
  const info: ApiErrorInfo = { retryAfter: parseRetryAfter(response.headers.get('Retry-After')) };
  try {
    const body = (await response.json()) as { detail?: unknown; code?: unknown; request_id?: unknown };
    if (typeof body.detail === 'string') info.detail = body.detail;
    else if (body.detail) info.detail = JSON.stringify(body.detail);
    if (typeof body.code === 'string') info.code = body.code;
    if (typeof body.request_id === 'string') info.requestId = body.request_id;
  } catch {
    /* body was not JSON */
  }
  return info;
}

async function request<S extends z.ZodType>(
  method: 'GET' | 'POST',
  path: string,
  schema: S,
  options: { params?: Params; body?: unknown; signal?: AbortSignal } = {},
): Promise<z.output<S>> {
  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.params), {
      method,
      headers: options.body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('Could not reach the GraphSense server.', 0);
  }

  if (!response.ok) {
    const info = await readError(response);
    throw new ApiError(info.detail ?? `The server responded with ${response.status}.`, response.status, info);
  }

  const json: unknown = await response.json().catch(() => null);
  const parsed = schema.safeParse(json);
  if (!parsed.success) {
    throw new ApiError('The server sent a response this app could not read.', response.status, parsed.error.message);
  }
  return parsed.data;
}

export const apiGet = <S extends z.ZodType>(path: string, schema: S, params?: Params, signal?: AbortSignal) =>
  request('GET', path, schema, { params, signal });

export const apiPost = <S extends z.ZodType>(path: string, schema: S, body: unknown, signal?: AbortSignal) =>
  request('POST', path, schema, { body, signal });

/** A short, human message for any error. */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.isNetwork) return 'GraphSense could not reach the server. Check that the backend is running, then try again.';
    if (error.isDatasetNotReady) return 'The data for this workspace hasn’t been loaded yet. Your administrator loads it, and this page will work once they have.';
    if (error.code === 'validation_error') return 'The server could not use that request. Please try again.';
    if (error.status >= 500) return 'The server ran into a problem. Please try again in a moment.';
    return error.detail ?? error.message;
  }
  if (error instanceof Error) return error.message;
  return 'Something went wrong. Please try again.';
}
