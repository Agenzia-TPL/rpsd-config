# RPSD local icons

The UI uses local SVG symbols from `rpsd-icons.svg`.

Source policy:

- icons are stored in this repository and served through Django static files;
- runtime pages must not depend on icon CDN URLs;
- new icons must be added as `<symbol>` elements with stable ids;
- after editing icons, run `collectstatic --noinput` in the `rpsd-config`
  runtime and verify that `icons/rpsd-icons.svg` is collected.

The current symbols are small line icons authored for the RPSD UI.
