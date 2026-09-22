const MAX_BASELINES = 100;
const MAX_BASELINE_BYTES = 64 * 1024 * 1024;

async function openReviewStore(database = globalThis.indexedDB) {
  if (!database) throw new Error("reviewStorageError");
  const connection = await new Promise((resolve, reject) => {
    let blocked = false;
    const request = database.open("signbridge-visual-review", 1);
    request.onupgradeneeded = () =>
      request.result.createObjectStore("baselines", { keyPath: "key" });
    request.onsuccess = () => {
      if (blocked) request.result.close();
      else resolve(request.result);
    };
    request.onerror = () => reject(new Error("reviewStorageError"));
    request.onblocked = () => {
      blocked = true;
      reject(new Error("reviewStorageError"));
    };
  });
  connection.onversionchange = () => connection.close();

  function read(key) {
    return new Promise((resolve, reject) => {
      const transaction = connection.transaction("baselines", "readonly");
      const request = transaction.objectStore("baselines").get(key);
      transaction.oncomplete = () => resolve(request.result || null);
      transaction.onabort = transaction.onerror = () =>
        reject(new Error("reviewStorageError"));
    });
  }

  function update(key, expectedToken, record, signal) {
    return new Promise((resolve, reject) => {
      signal?.throwIfAborted();
      const transaction = connection.transaction("baselines", "readwrite");
      const abort = () => transaction.abort();
      signal?.addEventListener("abort", abort, { once: true });
      const store = transaction.objectStore("baselines");
      let failure = "reviewStorageError";
      const request = store.getAll();
      request.onsuccess = () => {
        const previous = request.result.find((item) => item.key === key);
        if ((previous?.token || null) !== expectedToken) {
          failure = "reviewBaselineChanged";
          transaction.abort();
          return;
        }
        if (record) {
          const others = request.result.filter((item) => item.key !== key);
          if (
            !(record.image instanceof Blob) ||
            others.some((item) => !(item.image instanceof Blob))
          ) {
            failure = "reviewImageMismatch";
            transaction.abort();
            return;
          }
          const size = others.reduce(
            (sum, item) => sum + item.image.size,
            record.image.size,
          );
          if (others.length >= MAX_BASELINES || size > MAX_BASELINE_BYTES) {
            failure = "reviewStorageFull";
            transaction.abort();
            return;
          }
          store.put(record);
        } else store.delete(key);
      };
      transaction.oncomplete = () => {
        signal?.removeEventListener("abort", abort);
        resolve();
      };
      transaction.onabort = transaction.onerror = () => {
        signal?.removeEventListener("abort", abort);
        reject(signal?.aborted ? signal.reason : new Error(failure));
      };
    });
  }

  return { read, update, close: () => connection.close() };
}

export { openReviewStore };
