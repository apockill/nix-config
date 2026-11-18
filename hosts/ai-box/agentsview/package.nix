# agentsview (github.com/kenn-io/agentsview, MIT): the upstream release binary for linux arm64.
# It embeds its web UI; building from source needs Go 1.27 plus an npm tree with a git
# dependency, for no gain over the release (a CGO Go binary, glibc + libstdc++ only).
{
  lib,
  stdenv,
  fetchurl,
  autoPatchelfHook,
}:
stdenv.mkDerivation rec {
  pname = "agentsview";
  version = "0.47.0";

  src = fetchurl {
    url = "https://github.com/kenn-io/agentsview/releases/download/v${version}/agentsview_${version}_linux_arm64.tar.gz";
    hash = "sha256-WHk2xgDs7xoLGOyr84THXE6lA8N/kDLvERfAI1RO3qo=";
  };
  sourceRoot = ".";

  nativeBuildInputs = [ autoPatchelfHook ];
  buildInputs = [ stdenv.cc.cc.lib ];
  dontStrip = true;

  installPhase = ''
    runHook preInstall
    install -Dm755 agentsview $out/bin/agentsview
    runHook postInstall
  '';

  meta = {
    description = "Browse, search and track the cost of coding-agent sessions";
    homepage = "https://github.com/kenn-io/agentsview";
    license = lib.licenses.mit;
    platforms = [ "aarch64-linux" ];
    mainProgram = "agentsview";
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
  };
}
