import { I, b, c, a } from "../../browser-BISJ9naB.js";
function toArrayBuffer(view) {
  const { buffer, byteOffset, byteLength } = view;
  if (buffer instanceof ArrayBuffer) {
    return buffer.slice(byteOffset, byteOffset + byteLength);
  }
  const ab = new ArrayBuffer(byteLength);
  new Uint8Array(ab).set(new Uint8Array(buffer, byteOffset, byteLength));
  return ab;
}
function createNodeImageDataToBufferConverter(sharp) {
  return async (getImageData, imageType = "image/webp", imageQuality) => {
    const imageData = getImageData();
    const { width, height, data } = imageData;
    let sharpInstance = sharp(Buffer.from(data), {
      raw: {
        width,
        height,
        channels: 4
        // RGBA
      }
    });
    let buffer;
    switch (imageType) {
      case "image/webp":
        buffer = await sharpInstance.webp({
          quality: imageQuality
        }).toBuffer();
        break;
      case "image/png":
        buffer = await sharpInstance.png().toBuffer();
        break;
      case "image/jpeg":
        buffer = await sharpInstance.flatten({ background: { r: 255, g: 255, b: 255 } }).jpeg({
          quality: imageQuality
        }).toBuffer();
        break;
      default:
        throw new Error(`Unsupported image type: ${imageType}`);
    }
    return buffer;
  };
}
function createNodeCanvasImageDataToBlobConverter(createCanvas) {
  return async (getImageData, imageType = "image/webp", _imageQuality) => {
    const imageData = getImageData();
    const { width, height } = imageData;
    const canvas = createCanvas(width, height);
    const ctx = canvas.getContext("2d");
    ctx.putImageData(imageData, 0, 0);
    let buffer;
    switch (imageType) {
      case "image/webp":
        buffer = canvas.toBuffer("image/webp");
        break;
      case "image/png":
        buffer = canvas.toBuffer("image/png");
        break;
      case "image/jpeg":
        buffer = canvas.toBuffer("image/jpeg");
        break;
      default:
        throw new Error(`Unsupported image type: ${imageType}`);
    }
    return buffer;
  };
}
function createCustomImageDataToBlobConverter(processor) {
  return async (getImageData, imageType = "image/webp", imageQuality) => {
    const imageData = getImageData();
    const bytes = await processor(imageData, imageType, imageQuality);
    return new Blob([toArrayBuffer(bytes)], { type: imageType });
  };
}
function createCustomImageDataToBufferConverter(processor) {
  return async (getImageData, imageType = "image/webp", imageQuality) => {
    const imageData = getImageData();
    return await processor(imageData, imageType, imageQuality);
  };
}
export {
  I as ImageConverterError,
  b as browserImageDataToBlobConverter,
  createCustomImageDataToBlobConverter,
  createCustomImageDataToBufferConverter,
  c as createHybridImageConverter,
  createNodeCanvasImageDataToBlobConverter,
  createNodeImageDataToBufferConverter,
  a as createWorkerPoolImageConverter
};
//# sourceMappingURL=index.js.map
