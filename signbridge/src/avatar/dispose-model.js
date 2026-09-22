function disposeModel(root) {
  const disposed = new Set();
  function release(resource) {
    if (!resource?.dispose || disposed.has(resource)) return;
    disposed.add(resource);
    resource.dispose();
  }
  root?.traverse((object) => {
    release(object.geometry);
    release(object.skeleton);
    const materials = Array.isArray(object.material)
      ? object.material
      : [object.material];
    for (const material of materials) {
      if (!material) continue;
      for (const value of Object.values(material))
        if (value?.isTexture) release(value);
      release(material);
    }
  });
}

export { disposeModel };
