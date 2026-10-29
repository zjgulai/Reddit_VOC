/**
 * A cache whose validity is bound to one published release generation.
 *
 * Every dataset loader used to hold a module-level singleton (`summaryPromise`,
 * `brandHealthCache`, ...) that was populated on first call and never invalidated.
 * A tab left open across the 07:05 publish therefore kept serving the previous
 * generation's numbers, with nothing on screen saying so, until the user hit
 * reload. The pointer itself was also cached forever, so even a manual refresh of
 * a dataset could resolve against a stale generation.
 *
 * The fix is to key every cached value by the release generation it was built for.
 * `release.generated_at_utc` is the pointer's own write time, so it advances on
 * every publish and is stable within one.
 */

export interface ReleaseKeyedCacheOptions {
  /**
   * How long a resolved pointer may be reused before it is revalidated against
   * the server. Short enough that a publish reaches an open tab, long enough that
   * a page full of hooks resolves the pointer once.
   */
  ttlMs?: number;
  /** Injectable clock, so tests can advance time without sleeping. */
  now?: () => number;
}

const DEFAULT_TTL_MS = 5 * 60 * 1000;

interface Entry<T> {
  key: string;
  value: T;
}

/**
 * Values keyed by release generation.
 *
 * `get(key, factory)` returns the memoized value for that generation, or runs the
 * factory and stores the result. A different key never sees the previous value, so
 * a publish cannot be masked by an older generation's cache entry. Only the most
 * recent generation is retained: holding older ones would keep large payloads
 * alive across publishes for no benefit.
 */
export class ReleaseKeyedCache<T> {
  private entry: Entry<T> | null = null;
  private pending: { key: string; promise: Promise<T> } | null = null;

  get(key: string, factory: () => Promise<T>): Promise<T> {
    if (this.entry && this.entry.key === key) {
      return Promise.resolve(this.entry.value);
    }
    if (this.pending && this.pending.key === key) {
      return this.pending.promise;
    }
    const promise = factory().then(
      (value) => {
        // Only adopt the result if no newer generation has been requested since.
        // Otherwise a slow response for generation N could overwrite N+1.
        if (!this.pending || this.pending.promise === promise) {
          this.entry = { key, value };
          this.pending = null;
        }
        return value;
      },
      (error: unknown) => {
        // A rejected fetch must never be cached: the next call has to retry.
        if (this.pending && this.pending.promise === promise) {
          this.pending = null;
        }
        throw error;
      },
    );
    this.pending = { key, promise };
    return promise;
  }

  /** Synchronous read of the currently cached generation, if any. */
  peek(key: string): T | null {
    return this.entry && this.entry.key === key ? this.entry.value : null;
  }

  clear(): void {
    this.entry = null;
    this.pending = null;
  }
}

interface PointerEntry<T> {
  promise: Promise<T>;
  resolvedAt: number;
}

/**
 * Revalidating cache for the release pointer itself.
 *
 * Unlike a dataset payload the pointer is tiny, so re-fetching it is cheap; the
 * cache exists only to collapse the burst of calls a single page render makes.
 * After `ttlMs` the next read starts a fresh fetch, which is what lets an open tab
 * discover a publish without a reload.
 */
export class ReleasePointerCache<T> {
  private current: PointerEntry<T> | null = null;
  private readonly ttlMs: number;
  private readonly now: () => number;

  constructor(options: ReleaseKeyedCacheOptions = {}) {
    this.ttlMs = options.ttlMs ?? DEFAULT_TTL_MS;
    this.now = options.now ?? (() => Date.now());
  }

  read(loader: () => Promise<T>): Promise<T> {
    const cached = this.current;
    if (cached && this.now() - cached.resolvedAt < this.ttlMs) {
      return cached.promise;
    }
    const promise = loader();
    this.current = { promise, resolvedAt: this.now() };
    promise.catch(() => {
      // A failed load must not pin the TTL: the next read retries immediately.
      if (this.current && this.current.promise === promise) {
        this.current = null;
      }
    });
    return promise;
  }

  /** Force the next read to hit the network. */
  invalidate(): void {
    this.current = null;
  }

  /** Mark the cached pointer as resolved now, so a just-fetched value is fresh. */
  touch(): void {
    if (this.current) this.current.resolvedAt = this.now();
  }
}
