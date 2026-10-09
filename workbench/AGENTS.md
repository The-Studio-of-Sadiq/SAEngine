# VS Code Agents Instructions

## Structural Engineering IDE architecture

This workspace is the Code - OSS application fork used to build the standalone SAEngine structural engineering IDE.

- Implement engineering features directly in the native Code - OSS workbench and application source.
- Never create or modify VS Code extensions for SAEngine functionality. Do not create extension manifests, VSIX packages, or extension-host implementations.
- Follow the contribution, command, view, service, and build conventions of this exact Code - OSS checkout. Inspect neighboring implementations before changing code.
- Keep computational runtimes outside the renderer and use desktop-side application services for process management.
- Keep the upstream source tree under the SAEngine repository's `workbench` directory and keep changes targeted.
- Be explicit about incomplete behavior; do not present placeholder actions as working project or solver features.

For the repository's existing project overview, coding standards, and build guidance, see [.github/copilot-instructions.md](.github/copilot-instructions.md).
