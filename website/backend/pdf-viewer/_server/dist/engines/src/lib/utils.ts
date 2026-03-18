// Returns a plain ArrayBuffer (no SharedArrayBuffer), sliced to the view’s region.
export function toArrayBuffer(view: ArrayBufferView): ArrayBuffer {
  const { buffer, byteOffset, byteLength } = view;
  if (buffer instanceof ArrayBuffer) {
    return buffer.slice(byteOffset, byteOffset + byteLength);
  }
  // SharedArrayBuffer (or unknown) → copy once
  const ab = new ArrayBuffer(byteLength);
  new Uint8Array(ab).set(new Uint8Array(buffer as ArrayBufferLike, byteOffset, byteLength));
  return ab;
}

// Ensures ImageData gets a Uint8ClampedArray backed by a real ArrayBuffer.
export function toClampedRGBA(
  data: ArrayBufferView | Uint8Array | Uint8ClampedArray,
): Uint8ClampedArray {
  if (data instanceof Uint8ClampedArray && data.buffer instanceof ArrayBuffer) return data;
  return new Uint8ClampedArray(toArrayBuffer(data as ArrayBufferView));
}
