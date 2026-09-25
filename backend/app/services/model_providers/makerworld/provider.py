"""MakerWorld model provider.

Static descriptor + per-request service factory for makerworld.com. The
``MakerWorldProvider`` instance is what gets registered in the shared
:class:`ModelProviderRegistry`; the actual API work lives in ``service.py``
(the per-request :class:`ProviderService`) and ``url.py`` (URL parsing and
canonicalisation). Credential handling is centralised here so route layers
never touch MakerWorld specifics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from backend.app.core.permissions import Permission
from backend.app.services.model_providers.base import (
    ModelProvider,
    ProviderAuthConfig,
    ProviderAuthType,
    ProviderResourceRef,
    ProviderService,
)
from backend.app.services.model_providers.makerworld import url as mw_url
from backend.app.services.model_providers.makerworld.auth import (
    get_stored_token,
    mark_cloud_token_invalid,
)
from backend.app.services.model_providers.makerworld.http import (
    MAKERWORLD_API_BASE,
    MAKERWORLD_CDN_HOSTS,
    MAKERWORLD_CHINA_API_BASE,
    MAKERWORLD_CHINA_DOWNLOAD_HOSTS,
    MAKERWORLD_CHINA_PROFILE_API_BASE,
    MAKERWORLD_CHINA_THUMBNAIL_HOSTS,
    MAKERWORLD_PROFILE_API_BASE,
)
from backend.app.services.model_providers.makerworld.service import MakerWorldService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.app.models.user import User


class MakerWorldProvider(ModelProvider):
    """MakerWorld descriptor: identity, URL routing, auth requirements, and the
    factory that builds a per-request :class:`MakerWorldService` seeded with the
    caller's stored Bambu Cloud bearer token.
    """

    source_type = "makerworld"
    display_name = "MakerWorld"
    host_patterns = ("makerworld.com",)
    host_name = "makerworld.com"
    design_api_base = MAKERWORLD_API_BASE
    profile_api_base = MAKERWORLD_PROFILE_API_BASE
    referer = "https://makerworld.com/"
    required_region: str | None = None
    canonical_instance_ids = False
    auth = ProviderAuthConfig(
        auth_type=ProviderAuthType.BAMBU_CLOUD_BEARER,
        display_label="Bambu Cloud sign-in",
        description=(
            "MakerWorld downloads reuse the Bambu Cloud account already stored in Bambuddy — "
            "there is no separate MakerWorld sign-in."
        ),
        setup_hint="Open the Profiles page and sign in to Bambu Cloud.",
    )
    default_folder_name = "MakerWorld"
    view_permission = Permission.MAKERWORLD_VIEW
    import_permission = Permission.MAKERWORLD_IMPORT

    async def build_service(
        self,
        *,
        db: AsyncSession,
        user: User | None,
        api_key_owner: User | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> ProviderService:
        """Build a per-request service seeded with the caller's stored Bambu
        Cloud bearer, mirroring ``cloud.build_authenticated_cloud``.

        ``api_key_owner`` is the API key's owning user for API-keyed calls
        (see ``resolve_api_key_cloud_owner``); MakerWorld uses it as the
        fallback identity when ``user`` is None. Like the cloud integration, a
        rejected token is recorded so the whole app agrees the sign-in is dead
        rather than each feature failing on its own — including auth-disabled
        single-user installs, where ``user_id=None`` records the *global*
        flag those installs read back on the status endpoints.
        """
        identity = user if user is not None else api_key_owner
        token, _email, region = await get_stored_token(db, identity)
        user_id = identity.id if identity is not None else None
        return MakerWorldService(
            client=client,
            auth_token=token,
            user=identity,
            on_auth_failure=lambda: mark_cloud_token_invalid(user_id),
            # The SSRF allowlists are the provider's declared seams — the
            # service must not hardcode its own copies (symmetric pair,
            # ``fetch_thumbnail`` / ``download``).
            thumbnail_hosts=self.thumbnail_hosts(),
            download_hosts=self.download_hosts(),
            design_api_base=self.design_api_base,
            profile_api_base=self.profile_api_base,
            referer=self.referer,
            account_region=region,
            required_region=self.required_region,
            canonical_instance_ids=self.canonical_instance_ids,
        )

    def parse_url(self, url: str) -> ProviderResourceRef:
        return mw_url.parse_url(url, host_name=self.host_name, source_type=self.source_type)

    def canonical_url(self, ref: ProviderResourceRef) -> str:
        return mw_url.canonical_url(ref, host_name=self.host_name)

    def source_url_filter(self, column, external_id: str):
        """Whole-model key plus every per-plate key — MakerWorld's canonical
        shape appends ``#profileId-{n}`` for plate-level dedupe (see
        ``url.canonical_url``), so the already-imported detection must match
        both. The ``#profileId-`` fragment lives here with the descriptor
        because it is part of this provider's URL contract."""
        prefix = self.canonical_url(ProviderResourceRef(source_type=self.source_type, external_id=external_id))
        return (column == prefix) | (column.like(f"{prefix}#profileId-%"))

    def thumbnail_hosts(self) -> tuple[str, ...]:
        return MAKERWORLD_CDN_HOSTS

    def download_hosts(self) -> tuple[str, ...]:
        return MAKERWORLD_CDN_HOSTS


makerworld_provider = MakerWorldProvider()


class MakerWorldChinaProvider(MakerWorldProvider):
    source_type = "makerworld_cn"
    display_name = "MakerWorld China"
    host_patterns = ("makerworld.com.cn",)
    host_name = "makerworld.com.cn"
    design_api_base = MAKERWORLD_CHINA_API_BASE
    profile_api_base = MAKERWORLD_CHINA_PROFILE_API_BASE
    referer = "https://makerworld.com.cn/"
    required_region = "china"
    canonical_instance_ids = True
    default_folder_name = "MakerWorld China"

    def thumbnail_hosts(self) -> tuple[str, ...]:
        return MAKERWORLD_CHINA_THUMBNAIL_HOSTS

    def download_hosts(self) -> tuple[str, ...]:
        return MAKERWORLD_CHINA_DOWNLOAD_HOSTS


makerworld_china_provider = MakerWorldChinaProvider()
