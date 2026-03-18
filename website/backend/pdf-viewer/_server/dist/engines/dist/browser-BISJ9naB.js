class ImageConverterError extends Error {
  constructor(message) {
    super(message);
    this.name = "ImageConverterError";
  }
}
const browserImageDataToBlobConverter = (getImageData, imageType = "image/webp", quality) => {
  if (typeof document === "undefined") {
    return Promise.reject(
      new ImageConverterError(
        "document is not available. This converter requires a browser environment."
      )
    );
  }
  const pdfImage = getImageData();
  const imageData = new ImageData(pdfImage.data, pdfImage.width, pdfImage.height);
  return new Promise((resolve, reject) => {
    const canvas = document.createElement("canvas");
    canvas.width = imageData.width;
    canvas.height = imageData.height;
    canvas.getContext("2d").putImageData(imageData, 0, 0);
    canvas.toBlob(
      (blob) => {
        if (blob) {
          resolve(blob);
        } else {
          reject(new ImageConverterError("Canvas toBlob returned null"));
        }
      },
      imageType,
      quality
    );
  });
};
function createWorkerPoolImageConverter(workerPool) {
  const converter = (getImageData, imageType = "image/webp", quality) => {
    const pdfImage = getImageData();
    const dataCopy = new Uint8ClampedArray(pdfImage.data);
    return workerPool.encode(
      {
        data: dataCopy,
        width: pdfImage.width,
        height: pdfImage.height
      },
      imageType,
      quality
    );
  };
  converter.destroy = () => workerPool.destroy();
  return converter;
}
function createHybridImageConverter(workerPool) {
  const converter = async (getImageData, imageType = "image/webp", quality) => {
    try {
      const pdfImage = getImageData();
      const dataCopy = new Uint8ClampedArray(pdfImage.data);
      return await workerPool.encode(
        {
          data: dataCopy,
          width: pdfImage.width,
          height: pdfImage.height
        },
        imageType,
        quality
      );
    } catch (error) {
      console.warn("Worker encoding failed, falling back to main-thread Canvas:", error);
      return browserImageDataToBlobConverter(getImageData, imageType, quality);
    }
  };
  converter.destroy = () => workerPool.destroy();
  return converter;
}
export {
  ImageConverterError as I,
  createWorkerPoolImageConverter as a,
  browserImageDataToBlobConverter as b,
  createHybridImageConverter as c
};
//# sourceMappingURL=browser-BISJ9naB.js.map
