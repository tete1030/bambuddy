# MakerWorld China import design

Status: core China URL-to-Library implementation on this feature branch;
not deployed. The iOS Share Sheet shortcut and live Library smoke test remain
follow-up gates.

Base: `v1.2.5.6` (`d80414b518b602448192abd74506369b523cf29b`), the latest
non-prerelease release when this branch was created on 2026-09-26.

## Goal and scope

Accept a `makerworld.com.cn` model link, let the user choose the intended
print profile, and save that profile's original 3MF in Bambuddy's Library.
An iOS Share Sheet shortcut should be able to perform the same flow without
opening desktop Bambu Studio. Success means a real Library file ID was
returned and the file can be found again. Slicing and printer dispatch are
separate, explicit actions.

The first implementation supports full model URLs such as
`https://makerworld.com.cn/zh/models/2587619-...#profileId-2978680`.
Short links and app-specific share formats require samples before they are
added to the accepted URL set.

Out of scope: automatic printing, bypassing MakerWorld access controls,
storing browser cookies, replacing Bambu Cloud login, or silently choosing
the first of several print profiles.

## Evidence and constraints

- The existing global provider only claims `makerworld.com`; its metadata
  and signed-download endpoints use `api.bambulab.com`, and its CDN host
  allowlist contains `.com` hosts only.
- Public design ID `2587619` resolves on both regions but identifies
  different designs: the China response has `modelId` beginning `CN`, while
  the global response has a different `modelId` beginning `US`. A domain
  rewrite would import the wrong model.
- The China design-service endpoints
  `/v1/design-service/design/2587619` and `/instances` returned public
  metadata from `api.bambulab.cn` in a read-only probe. For this sample,
  the URL fragment `2978680` is `instances[].id` (instance ID); its internal
  `instances[].profileId` is `151216040`.
- With a China-region Bambu Cloud token, the corresponding
  `api.bambulab.cn/v1/iot-service/api/user/profile/{profileId}` request
  returned a signed URL on `model-file.bambulab.cn`. A four-byte range
  request returned HTTP 206 and the ZIP magic used by 3MF. No credential,
  signed URL, or file body is included here.
- `LibraryFile.source_type` is a 32-character string and `source_url` is a
  512-character string. Distinct China source values fit the existing schema;
  no database migration is expected for the proposed path.
- Bambuddy stores one Bambu Cloud token and region per user. The current
  MakerWorld provider reads the token but discards the stored region. An
  expired token still requires reauthentication through the existing UI.

The upstream China support report is
[`maziggy/bambuddy#1723`](https://github.com/maziggy/bambuddy/issues/1723).
It was closed for inactivity, not shipped as a fix.

## Recommended architecture

Add a `makerworld_cn` provider alongside the existing `makerworld` provider.
Share the transport implementation where the response shapes agree, but pass
an immutable region configuration into each service instance. Do not switch
module-level global URLs or rewrite numeric IDs. The registry already routes
`/makerworld/resolve` by host, and `/makerworld/import` already accepts a
`source_type` field that defaults to `makerworld` for old callers.

| Concern | Global provider | China provider |
| --- | --- | --- |
| `source_type` | `makerworld` | `makerworld_cn` |
| Model host | `makerworld.com` | `makerworld.com.cn` |
| API host | `api.bambulab.com` | `api.bambulab.cn` |
| Default folder | `MakerWorld` | `MakerWorld China` |
| Cloud credential | Existing global bearer | Existing China bearer |
| Permissions | `makerworld:view/import` | Reuse `makerworld:view/import` |

Use exact host allowlists for China thumbnails and signed file downloads,
initially `makerworld.bblmw.cn`, `public-cdn.bblmw.cn`, and
`model-file.bambulab.cn`. Keep the existing redirect restrictions, size
caps, ZIP validation, and rule that the bearer never goes to a CDN. Add a
host only after a real response demonstrates it is needed; do not allow
arbitrary `*.cn` downloads.

Reject a China import when the selected user's stored token is for the
global region. A local region mismatch is not proof that the token expired,
so it must not set `cloud_token_invalid_at`. Preserve the current global
flow and its legacy API defaults.

## ID and source URL contract

Keep these values distinct throughout resolve, import, and persistence:

| Value | Example | Purpose |
| --- | --- | --- |
| Design ID | `2587619` | Numeric ID in `/models/{id}`; only unique within a region |
| Model ID | `CN91056c50e00657` | Alphanumeric `design.modelId` for the download API |
| Instance ID | `2978680` | ID in the page's `#profileId-...` fragment |
| Profile ID | `151216040` | Internal `profileId` required by the signed-download API |

On resolve, match the fragment against `instances[].id`, then return both
the selected instance ID and its internal profile ID. If the fragment is
unknown, report a selection error; never use it as a download profile ID.
If the URL has no fragment and multiple instances, require a choice. One
instance may be selected automatically, with its identity shown to the user.

For China Library rows, use the real China page URL with the *instance ID*
as the per-profile canonical `source_url`. This makes repeated imports
idempotent, keeps the two regions independent, and opens the correct profile
on MakerWorld. `ProviderDownloadInfo` needs a separate optional internal
profile ID: `ref.sub_id` can remain the canonical instance key while the
import response reports the profile ID used for download. Leave existing
global source URLs unchanged; test their historical dedupe behavior.

## API and UI changes

1. Add `MakerWorldChinaProvider` registration and region-configured API,
   referer, and CDN handling under `backend/app/services/model_providers/`.
   Keep shared route code responsible for permissions, Library storage, and
   dedupe.
2. Add response fields to `POST /api/v1/makerworld/resolve`:
   `source_type`, `selected_instance_id`, `selected_profile_id`, and a
   region-correct `source_page_url`. Preserve existing response fields for
   global callers. The frontend must pass the returned `source_type` to
   `POST /api/v1/makerworld/import`; the endpoint's existing default keeps
   older clients working.
3. In the China provider, validate the requested internal profile belongs
   to the resolved design, map it back to its instance ID, and use the China
   alphanumeric model ID to request the signed URL. If `instance_id` is
   supplied too, reject a mismatch rather than importing another plate.
4. Make `/makerworld/status` report download eligibility for the selected
   provider or region, while retaining today's default for old clients.
   Include both source types in recent imports and identify the region in
   each row. Extend the thumbnail proxy and frontend CDN rewriting to the
   exact China hosts. Replace international-only "Open on MakerWorld" URL
   construction with the returned page URL.
5. Keep user-visible text in translation keys and update all locale files
   according to `CONTRIBUTING.md`. Changes to the MakerWorld page need
   before/after screenshots and a companion end-user wiki update if sent
   upstream.

## iOS Share Sheet flow

Update the existing shortcut after the backend contract is available:

1. Accept a shared China model URL without replacing its domain. Resolve
   only documented full URLs; verify any short-link expansion against an
   exact MakerWorld host allowlist.
2. Call `resolve` using a Bambuddy API key owned by the user with the China
   Cloud login. Grant `makerworld:view`, `makerworld:import`, and
   `library:read_own` (or `library:read_all` for a broader key) so the
   shortcut can verify the imported file. Never place the Bambu Cloud
   bearer in the shortcut.
3. If the link specifies an instance, use its mapped internal profile ID.
   If it does not and several profiles exist, show a chooser with titles;
   do not silently import the first one.
4. Call `import` with `model_id`, `source_type`, `instance_id`, and
   `profile_id`. Accept success only after the response contains a Library
   file ID and a follow-up Library lookup confirms that file exists.
   Distinguish "already in Library" from a new import and surface errors.

The shortcut stops at Library storage. A later user action can use the
existing server-side slicer, inspect the resulting `.gcode.3mf`, and decide
whether to print. No printer command is part of this import feature.

## Tests and acceptance

- URL tests: full China URL, locale path, slug, fragment, unsupported host,
  malformed ID, and no accidental cross-region rewrite.
- Provider tests: both regions with the same numeric design ID; China
  `instance.id` to `profileId` mapping; correct CN API host, model ID, and
  referer; missing/mismatched profile; account-region mismatch without
  invalidating a valid token.
- Transport tests: each allowed China CDN host, private/foreign hosts
  rejected, redirect refusal, response size cap, signed query preservation,
  and no bearer sent to CDN. Mock all credentials and signed URLs.
- Route and UI tests: additive `source_type` contract, legacy global
  default, real China source URL, duplicate import, recent-import region,
  thumbnail proxy, profile selection, and an accurate success state.
- Staging smoke: resolve a public China model, select the intended profile,
  import its full 3MF into a disposable Library, query the returned file ID,
  inspect the ZIP/3MF, then repeat to prove dedupe. Repeat one global import
  to detect regressions. Do not send a print command during this gate.
- Mobile smoke: share a link with a fragment and one without a fragment;
  verify selection, file identity, and both success and failure messages.

Keep the public sample payloads used in automated tests small and scrubbed
of bearer tokens, signed URL query strings, cookies, and account data.

## Delivery sequence and estimate

1. Backend provider, exact-host safety rules, and ID mapping: 1.5-2.5 days.
2. Additive API contract, MakerWorld UI, and locale updates: 1-1.5 days.
3. iOS shortcut and profile chooser: 0.5-1 day.
4. Automated tests, staged import, and regression checks: 1.5-2 days.

Estimated complete path: 5-8 developer days, including a modest allowance
for upstream API variation. The core China URL-to-Library path can be
verified earlier. Captcha challenges, additional signed-file hosts, or
different mobile share URL shapes are the main schedule uncertainties.

This release-tag branch is intended for local design and implementation.
Before an upstream PR, follow `CONTRIBUTING.md`: agree on an assigned issue,
rebase the implementation onto current `dev`, and prepare companion wiki
documentation. Do not deploy the fork to an existing Bambuddy installation
until its database and Docker configuration are backed up and the staged
import and global regression gates pass.

## Implementation checkpoint

The branch now registers `makerworld_cn` separately, maps China page instance
IDs to internal download profile IDs, checks the stored Bambu Cloud region,
keeps China source URLs and default Library folder separate, and uses exact
China CDN hosts. The existing `/makerworld/resolve`, `/import`, `/status`, and
`/recent-imports` routes expose the additive region fields. The MakerWorld
page passes the returned source type, shows the selected instance and region
mismatch, proxies China thumbnails, and opens the regional source page.

Automated coverage uses synthetic credentials and download URLs for routing,
mapping, region rejection, exact CDN hosts, idempotent Library persistence,
and the frontend China import flow. A prior read-only probe confirmed the
public China metadata and a four-byte signed 3MF response; it did not save a
full file in a Library. Before declaring the feature ready for use, run the
staging and mobile smoke gates above against a disposable installation and
verify the full 3MF, duplicate import, and Library lookup. Do not infer that
the existing live Unraid Bambuddy instance has this code.
