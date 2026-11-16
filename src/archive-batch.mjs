// Stop dispatching at the deadline; drain in-flight work before returning or throwing.
export async function archiveBatch(items, work, { limit = 50, budgetMs = 15000, concurrency = 3, shouldYield = () => false, signal } = {}) {
  if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > 3) throw Error('INVALID_ARCHIVE_CONCURRENCY');
  const deadline = performance.now() + budgetMs;
  let next = 0, failed = false;
  const worker = async () => {
    while (!failed && next < items.length && next < limit && !signal?.aborted && !shouldYield() && performance.now() < deadline) {
      const item = items[next++];
      try { await work(item); }
      catch (error) { failed = true; throw error; }
    }
  };
  const results = await Promise.allSettled(Array.from({ length: concurrency }, () => worker()));
  const failure = results.find(result => result.status === 'rejected');
  if (failure) throw failure.reason;
}
