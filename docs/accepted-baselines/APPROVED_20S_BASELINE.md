# Approved 20s visual baseline

This checkpoint preserves the exact local source snapshot that reproduced the user-approved `slice-final(1).mp4` render plan byte-for-byte (after normalizing asset paths).

- Source snapshot SHA-256: `bd5737dc9124d5d6e1f11784b0df89edd969aedcd46c43c18b915a47cc2a5fe1`
- Approved render plan SHA-256: `20377e428db29bf33c86ae446f7e1bb33061e3c16b986a809a863f8874c91ff3`
- Approved 20s video SHA-256: `c9cd164cafaba17139923d6ae9a39ca77f48fc0b0bcbde86a9686e3d1c3c93a0`
- Full render from same plan SHA-256: `8f62a9a556e855b866307c9bdcc90f11ccd59ebf1e6d2715a6c65c6ff0e91524`
- Acceptance package result: 49 story beats, 79 visual assets, 79 motion cues, 99.317551 s.
- Local regression tests on the preserved snapshot: 12/12 PASS.

This is the protected visual baseline. New cutout work must be additive and conservative: the proven first-pass extraction stays unchanged; a second refinement pass may only split clearly isolated major secondary objects and must never explode the scene into small fragments or disturb source-relative composition.
