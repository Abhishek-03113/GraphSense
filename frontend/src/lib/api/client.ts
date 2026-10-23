import type { z } from 'zod';

/** Base URL of the GraphSense API, including the `/api` prefix. Override with VITE_API_BASE_URL. */
export const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL as string | undefined) || 'http://localhost:8000/api';

export class ApiError extends Error {
  readonly status: number;
  readonly detail?: string;

  constructor(message: string, status: number, detail?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }

  /** True when the server could not be reached at all. */
  get isNetwork(): boolean {
    return this.status === 0;
  }
}

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

async function readDetail(response: Response): Promise<string | undefined> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === 'string') return body.detail;
    if (body.detail) return JSON.stringify(body.detail);
  } catch {
    /* body was not JSON */
  }
  return undefined;
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
    const detail = await readDetail(response);
    throw new ApiError(detail ?? `The server responded with ${response.status}.`, response.status, detail);
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
    return error.detail ?? error.message;
  }
  if (error instanceof Error) return error.message;
  return 'Something went wrong. Please try again.';
}
