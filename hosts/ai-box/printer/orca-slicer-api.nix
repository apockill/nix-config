# orca-slicer-api (github.com/maziggy/orca-slicer-api, AGPL-3.0): the HTTP wrapper around a
# slicer CLI that Bambuddy's slicer sidecar images run. Pinned to the bambuddy/profile-resolver
# branch, the one those images build from.
{
  lib,
  buildNpmPackage,
  fetchFromGitHub,
  fetchpatch,
  makeWrapper,
  nodejs_22,
}:
buildNpmPackage {
  pname = "orca-slicer-api";
  version = "1.0.0-unstable-2026-11-13";

  src = fetchFromGitHub {
    owner = "maziggy";
    repo = "orca-slicer-api";
    rev = "0bb2332e44d2454df4d643424cbb0d19b4883581";
    hash = "sha256-yYtPfKWDr+8g6jm/eOM5ZtviCgvXuZ/utYeMNr8q98o=";
  };
  patches = [
    # An optional `filamentMap` on POST /slice, passed to the CLI as --filament-map in
    # Manual mode: the one place Bambu Studio reads which nozzle each filament prints from.
    # Bambuddy's half is maziggy/bambuddy#3270 (./default.nix).
    # https://github.com/drkostas/orca-slicer-api/commit/be9957c8cadefe46d8e7dd440cc106d6cf7defac
    # (branch dual-nozzle-filament-map, based 4 commits behind the rev above).
    # Remove once it merges into bambuddy/profile-resolver and the rev above includes it.
    (fetchpatch {
      name = "orca-slicer-api-filament-map.patch";
      url = "https://github.com/drkostas/orca-slicer-api/commit/be9957c8cadefe46d8e7dd440cc106d6cf7defac.patch";
      hash = "sha256-SvSOP0O7wadNy0M9ZBw9F89YKM1UCX5AxPWHmpI0omc=";
    })
  ];
  npmDepsHash = "sha256-M2WWAID4WbD/N+Tyc+AiIjC4Fsdo/SD/9paghwRcmN4=";
  nodejs = nodejs_22;

  nativeBuildInputs = [ makeWrapper ];

  # The server listens on every interface; take the address from $HOST, as ./slicer.nix
  # sets it to loopback.
  postPatch = ''
    substituteInPlace src/index.ts \
      --replace-fail "app.listen(port, () => {" "app.listen(Number(port), process.env.HOST ?? \"0.0.0.0\", () => {"
  '';

  # The patch's own unit test; vitest is already a dev dependency.
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    npx vitest run tests/unit/filament-map.spec.ts
    runHook postCheck
  '';

  # `npm run build` compiles to dist/, which the repo ignores, so npm pack (buildNpmPackage's
  # default install) would leave it out. Install what the sidecar image ships instead: the
  # compiled server and the production dependencies.
  installPhase = ''
    runHook preInstall
    npm prune --omit=dev --no-save
    mkdir -p $out/lib/orca-slicer-api
    cp -r dist/src $out/lib/orca-slicer-api/dist
    cp -r node_modules package.json $out/lib/orca-slicer-api/
    makeWrapper ${lib.getExe nodejs_22} $out/bin/orca-slicer-api \
      --add-flags $out/lib/orca-slicer-api/dist/index.js \
      --set-default NODE_ENV production
    runHook postInstall
  '';

  meta = {
    description = "REST API for slicing models with the OrcaSlicer or Bambu Studio CLI";
    homepage = "https://github.com/maziggy/orca-slicer-api";
    license = lib.licenses.agpl3Plus;
    mainProgram = "orca-slicer-api";
  };
}
