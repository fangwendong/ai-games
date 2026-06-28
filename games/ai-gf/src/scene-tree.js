export class SceneTree {
  constructor() {
    this.scenes = [];
  }

  add(scene) {
    this.scenes.push(scene);
    this.scenes.sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
    return scene;
  }

  update(dt) {
    for (const scene of this.scenes) {
      scene.update?.(dt);
    }
  }

  render(ctx) {
    for (const scene of this.scenes) {
      scene.render?.(ctx);
    }
  }
}
