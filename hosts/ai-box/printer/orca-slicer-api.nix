# orca-slicer-api (github.com/maziggy/orca-slicer-api, AGPL-3.0): the HTTP wrapper around a
# slicer CLI that Bambuddy's slicer sidecar images run. Pinned to the bambuddy/profile-resolver
# branch, the one those images build from.
{
  lib,
  buildNpmPackage,
  fetchFromGitHub,
  makeWrapper,
  nodejs_22,
}:
buildNpmPackage {
  pname = "orca-slicer-api";
  version = "1.0.0-unstable-2026-11-22";

  src = fetchFromGitHub {
    owner = "maziggy";
    repo = "orca-slicer-api";
    rev = "6ba12014216e39325e2f87fe51d728fa798d9118";
    hash = "sha256-A1k6/ebUFFcaaDRx6Pq7kf0tHngz9WyV/1As3aWz8dY=";
  };
  npmDepsHash = "sha256-M2WWAID4WbD/N+Tyc+AiIjC4Fsdo/SD/9paghwRcmN4=";
  nodejs = nodejs_22;

  nativeBuildInputs = [ makeWrapper ];

  # The server listens on every interface; take the address from $HOST, as ./slicer.nix
  # sets it to loopback.
  postPatch = ''
    substituteInPlace src/index.ts \
      --replace-fail "app.listen(port, () => {" "app.listen(Number(port), process.env.HOST ?? \"0.0.0.0\", () => {"
  '';

  # The filament map's unit test (Bambuddy's half is maziggy/bambuddy#3270, ./default.nix);
  # vitest is already a dev dependency.
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
