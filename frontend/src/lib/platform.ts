const isMacLike = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);

/** Keyboard shortcut label for the command palette on this platform. */
export const SHORTCUT_LABEL = isMacLike ? '⌘K' : 'Ctrl K';
