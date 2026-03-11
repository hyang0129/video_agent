.PHONY: submodules-init submodules-update live2d-build live2d-test

# ── Submodule management ───────────────────────────────────────────────────────

submodules-init:
	git submodule update --init --recursive

submodules-update:
	git submodule update --remote --merge

# ── live2d ────────────────────────────────────────────────────────────────────

# Mesa software-renderer env vars required for headless EGL in the devcontainer.
# LIBGL_ALWAYS_SOFTWARE=1    → force Mesa llvmpipe (no GPU required)
# MESA_GL_VERSION_OVERRIDE   → expose OpenGL 3.3 Compatibility profile,
#                              which Cubism GLSL 1.20 shaders require.
LIVE2D_ENV = LIBGL_ALWAYS_SOFTWARE=1 MESA_GL_VERSION_OVERRIDE=3.3COMPAT

live2d-build:
	cmake -S vendor/live2d -B vendor/live2d/build -DCMAKE_BUILD_TYPE=Release
	cmake --build vendor/live2d/build --parallel

live2d-test:
	cd vendor/live2d && $(LIVE2D_ENV) python test_render.py --direct --scene 1
