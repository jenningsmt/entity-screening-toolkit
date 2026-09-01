<#
.SYNOPSIS
Runs `docker compose up --build` with GIT_COMMIT set from the current
checkout, so entity_screening/api's RunManifest.git_commit is populated
correctly instead of silently reading null.

.DESCRIPTION
.dockerignore excludes .git from the build context on purpose — no point
shipping this repo's whole history into a runtime image just to read one
commit hash. Dockerfile.api bakes GIT_COMMIT in at build time instead via
an ARG/ENV pair, and docker-compose.yml passes it through from this
environment variable. Without this script, `docker compose up --build` run
by hand simply won't have GIT_COMMIT set, and the Run provenance panel in
the UI will silently show a null commit again — this script exists
specifically so that doesn't have to be remembered by hand every time.

.EXAMPLE
scripts\compose-up.ps1
scripts\compose-up.ps1 -d
#>
$env:GIT_COMMIT = (git rev-parse HEAD).Trim()
Write-Host "Building with GIT_COMMIT=$env:GIT_COMMIT"
docker compose up --build @Args
