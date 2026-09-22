# Privacy

BBuddy is a local runtime for processing course materials that a user is authorized to access.

## Data stored locally

Depending on the workflow, BBuddy can store browser authentication state, downloaded course files, captions, source indexes, checkpoints, generated tutorials, and quality reports. These files are written to the user's selected data directory or the local BBuddy application-data directory. They are not part of the plugin package.

## Model processing

The Python runtime does not call a model API. A compatible host such as Codex reads selected source text to create the tutorial. The host's own data controls and privacy terms apply to that processing. Installing BBuddy locally does not make model inference offline.

## Network access

Online acquisition connects to the Blackboard and media URLs selected during the user's authorized session. The installation script connects to Python package indexes to install pinned dependencies. BBuddy has no project-operated telemetry or analytics service.

## Sensitive information

Do not submit passwords, cookies, browser storage, authorization headers, signed media URLs, real course files, or unredacted logs in GitHub issues. Use synthetic reproductions.

## Deletion

Users control the local data directory and can remove its contents when they no longer need saved authentication state or course artifacts. Removing the plugin does not automatically delete separately stored course data.
