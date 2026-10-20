/**
 * Last successful read of each workspace view, kept in memory for the page's lifetime.
 *
 * Returning to a tab paints this copy at once (marked busy) while the normal read revalidates it,
 * instead of unmounting the content into a skeleton. Keys always carry the identity scope
 * (platform, workspace, user, role), so a copy never crosses users or workspaces, and a denied
 * read forgets its entry. Only reads that fully succeeded are stored: errors and stale states never are.
 */
const entries = new Map<string, unknown>();
const LIMIT = 48;

export const viewCacheKey = (view: string, scope: object) => JSON.stringify([view, scope]);

export function readViewCache<T>(key: string): T | undefined {
  return entries.get(key) as T | undefined;
}

export function rememberView<T>(key: string, value: T) {
  entries.delete(key);
  entries.set(key, value);
  // Oldest first: Map keeps insertion order, and a write moves the key to the end.
  while (entries.size > LIMIT) entries.delete(entries.keys().next().value as string);
}

export function forgetView(key: string) {
  entries.delete(key);
}

export function clearViewCache() {
  entries.clear();
}
