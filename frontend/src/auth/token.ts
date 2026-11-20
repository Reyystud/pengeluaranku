// The access token lives in memory only (PRD 8.3): never localStorage, never a readable cookie.
let accessToken: string | null = null;
let onAuthLost: (() => void) | null = null;

export const getToken = (): string | null => accessToken;
export const setToken = (token: string | null): void => {
  accessToken = token;
};
export const setAuthLostHandler = (handler: (() => void) | null): void => {
  onAuthLost = handler;
};
export const notifyAuthLost = (): void => {
  accessToken = null;
  onAuthLost?.();
};
