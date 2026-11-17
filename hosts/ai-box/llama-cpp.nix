# Local LLM service running llama.cpp with CUDA (sm_87) on the Jetson AGX Orin.
# Serves Gemma 4 26B-A4B for background scheduled jobs with a 256K context window.
{
  config,
  lib,
  pkgs,
  ...
}:
{
  services.llama-cpp = {
    enable = true;
    # b9190 saves every cell of a slot in its SWA context checkpoints, up to the whole prompt
    # rather than the 1024-token window. With 4 slots in the unified KV cache, restoring one
    # of those (a slot taking a new prompt over ~1k tokens) finds no room in the 4608-cell SWA
    # cache and llama-server aborts ("checkpoint size mismatch", ggml-org/llama.cpp#23720).
    # Upstream's fix (#23981, first in b9473) stores only the cells inside the window.
    # Drop the patch once nixpkgs' llama-cpp is b9473 or newer; it then stops applying.
    package = (pkgs.llama-cpp.override { cudaSupport = true; }).overrideAttrs (old: {
      patches = (old.patches or [ ]) ++ [
        (pkgs.fetchpatch {
          name = "llama-cpp-23981-swa-checkpoints-non-masked-cells.patch";
          url = "https://github.com/ggml-org/llama.cpp/commit/236531595584fdb5f63f09bf4306cf982b757e6e.patch";
          hash = "sha256-e/DXZgys7oF/e7U5AR1EcIFulX/JlDSw//I+mAJnwqM=";
        })
      ];
    });
    host = "127.0.0.1";
    port = 8080;
    extraFlags = [
      "-hf"
      "unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q4_K_M"
      "-c"
      "262144"
      "-ctk"
      "q8_0"
      "-ctv"
      "q8_0"
      "-ngl"
      "999"
      "-fa"
      "on"
      # A small host-RAM prompt cache. The default (8192 MiB) fills within an hour of every
      # start and then holds ~8 GB of RAM for good (RSS ~23 -> ~31.5 GB), which the box's test
      # runs need. The prompts here are short (p50 ~380, max ~7k tokens), so a cache hit saves
      # a second or two at most. Not 0: without a cache, a slot that takes a new prompt keeps
      # the old one and restores a context checkpoint to reuse the ~13 tokens of chat template,
      # on nearly every request, which was slower (and, before the patch above, aborted once
      # prompts outgrew the 1024-token SWA window).
      "--cache-ram"
      "1024"
      "--alias"
      "gemma-4-26b-a4b"
    ];
  };

  # On Jetson AGX Orin, GPU access (/dev/nvmap, /dev/nvhost-*) requires group 'video'
  systemd.services.llama-cpp.serviceConfig = {
    SupplementaryGroups = [ "video" ];
    TimeoutStartSec = 1800;
  };
}
