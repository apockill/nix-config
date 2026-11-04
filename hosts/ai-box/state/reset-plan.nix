# The root reset's copy plan (see ./root-reset.nix): which declared paths to
# copy from the old root into the fresh one, and which to delete again from
# what was copied. Generated from aiBox.state.paths at build time.
#
#   copy P    P is kept (any class but ephemeral) and its nearest declared
#             ancestor is ephemeral, or it has none.
#   delete P  P is ephemeral and its nearest declared ancestor is kept, so the
#             copy of that ancestor brought P along.
#
# Paths without an action are covered by their ancestor's action. Actions are
# sorted by depth, so nesting works at any depth: copy A, delete A/B, copy
# A/B/C. A `*` segment matches any one name, here and when the plan runs.
#
# Takes `lib` and returns a function from aiBox.state.paths to the plan, a
# list of { action, path }.
{ lib }:
declared:
let
  segments = path: lib.tail (lib.splitString "/" path);
  depth = path: lib.length (segments path);
  isKept = path: declared.${path}.backup != "ephemeral";

  # Can `a` and `b` name the same path? Equal segments match, and a `*`
  # segment on either side matches anything.
  overlap =
    a: b:
    depth a == depth b
    && lib.all (pair: pair.fst == pair.snd || pair.fst == "*" || pair.snd == "*") (
      lib.zipLists (segments a) (segments b)
    );

  # The declarations that can name `path`'s ancestor at `d` segments deep.
  ancestorsAt =
    path: d:
    let
      prefix = "/" + lib.concatStringsSep "/" (lib.take d (segments path));
    in
    lib.filter (other: overlap other prefix) (lib.attrNames declared);

  # The declarations of `path`'s nearest declared ancestor, deepest first. With
  # `*` segments more than one can match; the plan copies when any of them is
  # ephemeral and deletes when any is kept (a copy that brings nothing along,
  # or a delete that finds nothing, is harmless).
  nearestAncestors =
    path:
    lib.findFirst (matches: matches != [ ]) [ ] (
      map (ancestorsAt path) (lib.reverseList (lib.range 1 (depth path - 1)))
    );

  actionFor =
    path:
    let
      ancestors = nearestAncestors path;
    in
    if isKept path then
      if ancestors == [ ] || lib.any (a: !isKept a) ancestors then "copy" else null
    else if lib.any isKept ancestors then
      "delete"
    else
      null;

  # Two declarations of the same depth that can name the same path must agree
  # on kept or not, or the order of their actions would decide what survives.
  conflicts = lib.filter ({ fst, snd }: fst < snd && overlap fst snd && isKept fst != isKept snd) (
    lib.cartesianProduct {
      fst = lib.attrNames declared;
      snd = lib.attrNames declared;
    }
  );

  steps = lib.filter (step: step.action != null) (
    map (path: {
      inherit path;
      action = actionFor path;
    }) (lib.attrNames declared)
  );
  # By depth, then by path so the plan only changes when the declarations do.
  shallowerFirst =
    a: b: if depth a.path != depth b.path then depth a.path < depth b.path else a.path < b.path;
  plan = lib.sort shallowerFirst steps;
in
if conflicts == [ ] then
  plan
else
  throw "aiBox.state.paths: ${
    lib.concatMapStringsSep ", " ({ fst, snd }: "\"${fst}\" and \"${snd}\"") conflicts
  } can name the same path but one is ephemeral and the other is kept."
