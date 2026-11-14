// Load the unchanged GLB skeleton and skin on CPU; omit textures only for audit.
import { readFileSync } from "node:fs";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

export async function loadSkinModel(path) {
  const bytes = readFileSync(path),
    jsonLength = bytes.readUInt32LE(12);
  const gltf = JSON.parse(
    bytes
      .subarray(20, 20 + jsonLength)
      .toString("utf8")
      .replace(/\0+$/, ""),
  );
  const bin = bytes.subarray(28 + jsonLength);
  delete gltf.images;
  delete gltf.textures;
  delete gltf.materials;
  gltf.meshes.forEach((mesh) =>
    mesh.primitives.forEach((primitive) => delete primitive.material),
  );
  const encoded = Buffer.from(JSON.stringify(gltf)),
    padded = Buffer.alloc(Math.ceil(encoded.length / 4) * 4, 32);
  encoded.copy(padded);
  const result = Buffer.alloc(28 + padded.length + bin.length);
  result.writeUInt32LE(0x46546c67);
  result.writeUInt32LE(2, 4);
  result.writeUInt32LE(result.length, 8);
  result.writeUInt32LE(padded.length, 12);
  result.writeUInt32LE(0x4e4f534a, 16);
  padded.copy(result, 20);
  result.writeUInt32LE(bin.length, 20 + padded.length);
  result.writeUInt32LE(0x004e4942, 24 + padded.length);
  bin.copy(result, 28 + padded.length);
  const loaded = await new GLTFLoader().parseAsync(
    result.buffer.slice(
      result.byteOffset,
      result.byteOffset + result.byteLength,
    ),
    "",
  );
  loaded.scene.updateMatrixWorld(true);
  loaded.scene.traverse((node) => {
    if (node.isSkinnedMesh) node.skeleton.update();
  });
  return loaded.scene;
}
