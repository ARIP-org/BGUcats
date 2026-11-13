// A profile photo, made ready on the phone (B1b; 02-architecture.md,
// "Storage"): cut to a square, scaled to at most 512 px and re-encoded as a
// JPEG of at most 200 KB. Drawing it on a canvas is also what drops
// whatever the camera wrote into the file (where, when, with what): the
// server refuses a picture that still carries it.

const SIDE = 512;
const MAX_BYTES = 200_000;
const QUALITIES = [0.86, 0.76, 0.66, 0.56, 0.46];

function decoded(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    // An <img> is turned the way the camera held it; a bitmap may not be.
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("not a picture this phone can open"));
    };
    image.src = url;
  });
}

const encoded = (canvas, quality) =>
  new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));

// file -> a JPEG Blob ready to upload.
export async function squareJpeg(file) {
  const image = await decoded(file);
  const cut = Math.min(image.naturalWidth, image.naturalHeight);
  if (!cut) throw new Error("not a picture this phone can open");
  for (let side = Math.min(SIDE, cut); side >= 128; side = Math.round(side * 0.75)) {
    const canvas = document.createElement("canvas");
    canvas.width = side;
    canvas.height = side;
    canvas
      .getContext("2d")
      .drawImage(image, (image.naturalWidth - cut) / 2, (image.naturalHeight - cut) / 2, cut, cut, 0, 0, side, side);
    for (const quality of QUALITIES) {
      const blob = await encoded(canvas, quality);
      if (blob && blob.size <= MAX_BYTES) return blob;
    }
  }
  throw new Error("this picture cannot be made small enough");
}
