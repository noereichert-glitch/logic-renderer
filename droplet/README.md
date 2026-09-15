# Stemma droplet

Drag sessions onto it → plants an alias (symlink) in the stemma folder; the
original never moves. Dropped Finder aliases are resolved to their originals.
Double-click → opens the stemma folder in Finder. Never triggers a render.

Rebuild after editing the source:

    osacompile -o ~/Music/Stemma/"Stemma Drop.app" stemma_droplet.applescript
