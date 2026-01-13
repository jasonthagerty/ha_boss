# Instance-Level Authorization Analysis

**Issue**: #144
**Date**: 2026-01-13
**Status**: Design Decision Required

## Executive Summary

This document analyzes the need for instance-level authorization in HA Boss and provides a recommendation based on current project state, MVP goals, and complexity trade-offs.

**Recommendation**: **Option 1 (Instance-Specific API Keys)** - Implement in Phase 4 (post-MVP), not urgent for current release.

---

## Current State Analysis

### Existing Authentication

**Implementation**: `ha_boss/api/dependencies.py`

```python
async def verify_api_key(api_key: str | None) -> None:
    """Verify API key if authentication is enabled."""
    if not service.config.api.auth_enabled:
        return
    if api_key not in service.config.api.api_keys:
        raise HTTPException(status_code=401, detail="Invalid API key")
```

**Current Behavior**:
- ✅ Simple API key authentication via `X-API-Key` header
- ✅ Enabled/disabled via `api.auth_enabled` config flag
- ✅ Global API keys in `api.api_keys` list
- ❌ **No per-instance access control** - any valid key accesses all instances

### Multi-Instance Architecture

**Configuration**: `ha_boss/core/config.py`

```yaml
home_assistant:
  instances:
    - instance_id: "home"
      url: "http://home.local:8123"
      token: "home-token"
    - instance_id: "cabin"
      url: "http://cabin.local:8123"
      token: "cabin-token"
```

**Instance Access**: All API routes accept `instance_id` query parameter (default: "default"):
- `GET /api/status?instance_id=home`
- `GET /api/entities?instance_id=cabin`
- `POST /api/healing/trigger?instance_id=home`

**Security Gap**: Currently, anyone with a valid API key can access ALL instances.

---

## Option Analysis

### Option 1: Instance-Specific API Keys

**Implementation**:

```yaml
api:
  auth_enabled: true
  api_keys:
    - key: "admin-key-abc123"
      instances: ["*"]  # All instances
    - key: "home-key-def456"
      instances: ["home"]  # Only home instance
    - key: "cabin-key-ghi789"
      instances: ["cabin"]  # Only cabin instance
```

**Code Changes Required**:

1. **Config Schema Update** (`ha_boss/core/config.py`):
```python
class APIKey(BaseModel):
    """API key with instance-level permissions."""
    key: str
    instances: list[str]  # List of instance_ids or ["*"] for all

class APIConfig(BaseModel):
    api_keys: list[APIKey] = Field(default_factory=list)  # Changed from list[str]
```

2. **Dependency Update** (`ha_boss/api/dependencies.py`):
```python
async def verify_api_key_for_instance(
    api_key: str | None,
    instance_id: str = Query("default"),
) -> None:
    """Verify API key has access to the requested instance."""
    # 1. Check if key is valid (existing logic)
    # 2. NEW: Check if instance_id in key.instances or "*" in key.instances
    # 3. Raise 403 Forbidden if no access
```

3. **Route Updates**: Add instance_id parameter to dependency in ALL routes (30+ routes):
```python
@router.get("/api/status")
async def get_status(
    instance_id: str = Query("default"),
    auth: None = Depends(verify_api_key_for_instance),  # NEW: needs instance_id
):
```

**Complexity**: ⭐⭐⭐ Medium
- **Files Changed**: 3-4 files
- **Lines Changed**: ~150 lines
- **Breaking Change**: Config schema change (requires migration)
- **Testing**: ~10 new test cases needed
- **Migration Path**: Support old `api_keys: list[str]` format, convert to new format

**Pros**:
- ✅ Simple to understand and configure
- ✅ Covers 80% of multi-tenant use cases
- ✅ No external dependencies
- ✅ Minimal performance impact
- ✅ Backward compatible with migration

**Cons**:
- ❌ No user management (just keys)
- ❌ No audit logging (who accessed what)
- ❌ No role-based permissions (read-only vs admin)
- ❌ Breaking config change (requires migration guide)

---

### Option 2: Full RBAC System

**Implementation**:

```yaml
api:
  auth_enabled: true
  users:
    - username: "admin"
      api_key: "admin-key-abc123"
      role: "admin"
      instances: ["*"]
      permissions: ["read", "write", "heal", "analyze"]
    - username: "viewer"
      api_key: "viewer-key-def456"
      role: "viewer"
      instances: ["home", "cabin"]
      permissions: ["read"]
```

**Code Changes Required**:

1. **New Models** (`ha_boss/api/models.py`):
```python
class Role(Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"

class Permission(Enum):
    READ = "read"
    WRITE = "write"
    HEAL = "heal"
    ANALYZE = "analyze"

class User(BaseModel):
    username: str
    api_key: str
    role: Role
    instances: list[str]
    permissions: list[Permission]
```

2. **Authorization Middleware** (`ha_boss/api/authorization.py` - NEW FILE):
```python
async def require_permission(
    permission: Permission,
    instance_id: str,
) -> Callable:
    """Decorator to require specific permission for instance."""
    # Complex permission checking logic
```

3. **Audit Logging** (`ha_boss/api/audit.py` - NEW FILE):
```python
async def log_api_access(
    user: User,
    instance_id: str,
    endpoint: str,
    action: str,
):
    """Log all API access for compliance."""
```

4. **Database Schema**: New table for audit logs
5. **Route Updates**: Add permission decorators to ALL routes

**Complexity**: ⭐⭐⭐⭐⭐ Very High
- **Files Changed**: 15+ files
- **Lines Changed**: ~500+ lines
- **New Dependencies**: Potentially need proper auth library (e.g., FastAPI-Users)
- **Database Changes**: New audit log table
- **Breaking Change**: Major config schema change
- **Testing**: ~50+ new test cases needed

**Pros**:
- ✅ Enterprise-grade authorization
- ✅ Fine-grained permissions
- ✅ Audit logging for compliance
- ✅ User management with roles
- ✅ Supports complex multi-tenant scenarios

**Cons**:
- ❌ **Massive scope** - 2-3 weeks of work
- ❌ Overkill for current MVP/early adopters
- ❌ Significant maintenance burden
- ❌ Adds complexity to every route
- ❌ Performance overhead (permission checks on every request)
- ❌ Breaking changes to config and API

---

### Option 3: Document Current Behavior (No Implementation)

**Implementation**: Add documentation clarifying that instance isolation is a deployment concern.

**Documentation Update** (`README.md`, `docs/DEPLOYMENT.md`):

```markdown
## Multi-Instance Security Model

HA Boss uses a **trust-based security model** for multi-instance deployments:

- **Single API Key Pool**: All configured API keys grant access to all instances
- **No Per-Instance Authorization**: Any authenticated user can access any instance
- **Recommended Deployment**:
  - For **single-tenant use** (one user/household): Use shared API key
  - For **multi-tenant use** (multiple customers): Deploy separate HA Boss instances

### Multi-Tenant Deployment Pattern

For managed service providers monitoring multiple customer homes:

**Approach**: Deploy separate HA Boss containers per customer/tenant

```yaml
# Customer A
docker run -e HA_URL=http://customer-a.local:8123 \
           -e HA_TOKEN=customer-a-token \
           -e API_KEYS=customer-a-api-key \
           ha-boss

# Customer B
docker run -e HA_URL=http://customer-b.local:8123 \
           -e HA_TOKEN=customer-b-token \
           -e API_KEYS=customer-b-api-key \
           ha-boss
```

**Benefits**:
- ✅ Complete isolation (data, access, failures)
- ✅ Simpler security model
- ✅ Independent scaling and updates
- ✅ No code changes needed

**When to Use Instance-Level Auth**: If managing 10+ instances in a single deployment,
consider implementing Option 1 (Instance-Specific API Keys) in a future release.
```

**Complexity**: ⭐ Minimal
- **Files Changed**: 2 files (README.md, docs/DEPLOYMENT.md)
- **Lines Changed**: ~50 lines of documentation
- **No Code Changes**
- **No Breaking Changes**
- **No Testing Required**

**Pros**:
- ✅ Zero implementation time
- ✅ No code complexity
- ✅ Deployment isolation is a valid security pattern
- ✅ Simpler to maintain
- ✅ No performance impact

**Cons**:
- ❌ Doesn't solve the problem if users want single deployment
- ❌ More complex deployment for multi-tenant scenarios
- ❌ Doesn't provide audit trail

---

## Use Case Analysis

### Target Users & Scenarios

**Primary Users (MVP Phase)**:
1. **Home Users** - Monitoring 1-2 HA instances (home + vacation home)
   - **Need**: Basic monitoring, don't need per-instance auth
   - **Solution**: Option 3 (document current behavior) is sufficient

2. **Power Users** - Monitoring 2-5 instances (multiple properties)
   - **Need**: Some separation, but trust-based model acceptable
   - **Solution**: Option 3 or Option 1 (nice to have)

**Future Users (Phase 4+)**:
3. **Managed Service Providers** - Monitoring 10+ customer instances
   - **Need**: Strong isolation, audit logging, compliance
   - **Solution**: Option 1 (minimum), Option 2 (ideal)

4. **Enterprise Users** - Large-scale deployments with governance
   - **Need**: RBAC, audit trails, compliance
   - **Solution**: Option 2 required

### User Demand Assessment

**Current Evidence**:
- ⚠️ No user-reported issues requesting this feature
- ⚠️ No GitHub issues or discussions about multi-tenant auth
- ⚠️ Project is in MVP/early adopter phase
- ✅ Issue #144 raised proactively during code review (good forward thinking)

**Conclusion**: **Low immediate demand**, but will become important if adoption grows.

---

## Complexity vs Benefit Analysis

| Aspect | Option 1 | Option 2 | Option 3 |
|--------|----------|----------|----------|
| **Implementation Time** | 2-3 days | 2-3 weeks | 1 hour |
| **Code Complexity** | Medium | Very High | None |
| **Maintenance Burden** | Low | High | None |
| **Breaking Changes** | Yes (config) | Yes (major) | No |
| **Testing Effort** | Medium | High | None |
| **Addresses Use Cases** | 80% | 100% | 50% |
| **Performance Impact** | Minimal | Moderate | None |
| **MVP Alignment** | ❌ Scope creep | ❌❌ Major scope creep | ✅ MVP-appropriate |

---

## Recommendation

### Primary Recommendation: **Option 3 (Document) + Defer Option 1**

**Immediate Action (This Sprint)**:
1. ✅ **Document current behavior** (Option 3)
   - Add security model section to README.md
   - Add multi-tenant deployment guide to docs/DEPLOYMENT.md
   - Clarify that instance isolation is deployment-level
   - Estimate: 1 hour

**Future Action (Phase 4 - Post-MVP)**:
2. ⏰ **Implement Option 1** (Instance-Specific API Keys)
   - Wait for user demand signal (3+ requests)
   - Implement when multi-tenant use cases emerge
   - Create migration guide for config schema change
   - Estimate: 2-3 days when prioritized

**Never Implement**:
3. ❌ **Option 2** (Full RBAC) - Scope too large for this project
   - Better served by external auth solutions (OAuth, LDAP, etc.)
   - Consider if HA Boss becomes a commercial SaaS product

### Rationale

**Why Option 3 Now**:
- ✅ **MVP Focus**: HA Boss is still in early phases, premature optimization
- ✅ **No User Demand**: No evidence users need this feature yet
- ✅ **Valid Pattern**: Deployment-level isolation is industry standard
- ✅ **Zero Risk**: Documentation doesn't introduce bugs or complexity
- ✅ **Rapid Value**: Clarifies security model for users immediately

**Why Defer Option 1**:
- ⏰ **Wait for Signal**: Implement when 3+ users request it
- ⏰ **Tech Debt**: Acceptable to add later, clean interfaces already exist
- ⏰ **Breaking Change**: Better to make config changes when user base is small
- ⏰ **Future-Proof**: Code structure already supports this extension

**Why Never Option 2**:
- ❌ **Over-Engineering**: Way beyond project scope and current needs
- ❌ **Maintenance**: Adds complexity that slows down all future work
- ❌ **Better Solutions**: If enterprise auth needed, use external OAuth/LDAP

---

## Implementation Plan (If Option 1 Selected)

**Note**: Only implement if user demand emerges. This is a contingency plan.

### Phase 1: Config Schema Update (Day 1)

**File**: `ha_boss/core/config.py`

```python
from pydantic import BaseModel, Field, model_validator

class APIKey(BaseModel):
    """API key with optional instance-level permissions."""

    key: str = Field(
        description="API key value"
    )
    instances: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Allowed instance IDs or ['*'] for all"
    )
    description: str | None = Field(
        default=None,
        description="Optional description of key purpose"
    )

class APIConfig(BaseModel):
    """REST API configuration."""

    # ... existing fields ...

    api_keys: list[str | APIKey] = Field(  # Support both formats!
        default_factory=list,
        description="Valid API keys (string or APIKey object)"
    )

    @model_validator(mode="after")
    def normalize_api_keys(self) -> "APIConfig":
        """Convert string keys to APIKey objects for backward compatibility."""
        normalized = []
        for key in self.api_keys:
            if isinstance(key, str):
                # Legacy format: convert to new format with wildcard
                normalized.append(APIKey(key=key, instances=["*"]))
            else:
                normalized.append(key)
        self.api_keys = normalized
        return self
```

**Tests**: `tests/core/test_config.py`

```python
def test_api_keys_backward_compatibility():
    """Test that old string format still works."""
    config = Config(api=APIConfig(
        api_keys=["old-key-123"]  # Old format
    ))
    assert len(config.api.api_keys) == 1
    assert config.api.api_keys[0].key == "old-key-123"
    assert config.api.api_keys[0].instances == ["*"]

def test_api_keys_new_format():
    """Test new instance-specific format."""
    config = Config(api=APIConfig(
        api_keys=[
            APIKey(key="admin-key", instances=["*"]),
            APIKey(key="home-key", instances=["home"]),
        ]
    ))
    assert config.api.api_keys[0].instances == ["*"]
    assert config.api.api_keys[1].instances == ["home"]
```

### Phase 2: Dependency Update (Day 2)

**File**: `ha_boss/api/dependencies.py`

```python
async def verify_api_key_for_instance(
    api_key: Annotated[str | None, Security(api_key_header)] = None,
    instance_id: str = Query("default", description="Instance identifier"),
) -> None:
    """Verify API key has access to the requested instance.

    Args:
        api_key: API key from X-API-Key header
        instance_id: Requested instance ID

    Raises:
        HTTPException: 401 if auth enabled and key invalid
        HTTPException: 403 if key doesn't have access to instance
    """
    try:
        service = get_service()

        # Skip auth if not enabled
        if not service.config.api.auth_enabled:
            return

        # Check if API key is provided
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key required. Provide X-API-Key header.",
            )

        # Find matching API key object
        matched_key = None
        for key_obj in service.config.api.api_keys:
            if key_obj.key == api_key:
                matched_key = key_obj
                break

        if not matched_key:
            logger.warning(f"Invalid API key attempt: {api_key[:8]}...")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

        # NEW: Check instance-level permission
        if "*" not in matched_key.instances and instance_id not in matched_key.instances:
            logger.warning(
                f"API key {api_key[:8]}... attempted access to "
                f"unauthorized instance: {instance_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key does not have access to instance: {instance_id}",
            )

        logger.debug(
            f"API key {api_key[:8]}... validated for instance: {instance_id}"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying API key: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication error",
        )
```

**Tests**: `tests/api/test_dependencies.py`

```python
@pytest.mark.asyncio
async def test_verify_api_key_wildcard_access():
    """Test that wildcard key can access all instances."""
    # Key with wildcard should access any instance
    # Test with instance_id="home", "cabin", "unknown"

@pytest.mark.asyncio
async def test_verify_api_key_instance_specific():
    """Test that instance-specific key is restricted."""
    # Key with instances=["home"] should:
    # - Allow access to instance_id="home"
    # - Deny access to instance_id="cabin" (403)

@pytest.mark.asyncio
async def test_verify_api_key_backward_compatibility():
    """Test that legacy string keys work as wildcards."""
    # Old format keys should behave as wildcard
```

### Phase 3: Route Migration (Day 2-3)

**Current Routes**: 30+ routes across 7 files need updates

**Strategy**: Automatic via FastAPI dependency injection (no route changes!)

Since we're using FastAPI's dependency system, we can update the global dependency:

**File**: `ha_boss/api/app.py`

```python
# Current (uses verify_api_key):
dependencies = [Depends(verify_api_key)]

# NEW (uses verify_api_key_for_instance):
dependencies = [Depends(verify_api_key_for_instance)]
```

**Magic**: FastAPI automatically injects `instance_id` from query parameters!
- ✅ No changes to individual routes needed
- ✅ Dependency resolver handles parameter extraction
- ✅ All 30+ routes automatically protected

**Testing**: Run full API test suite to ensure no regressions

### Phase 4: Documentation (Day 3)

**Files to Update**:
1. `README.md` - Security section
2. `docs/API.md` - Authentication guide
3. `config/config.yaml.example` - Show new format
4. `CHANGELOG.md` - Breaking change notice

**Migration Guide** (`docs/MIGRATION_INSTANCE_AUTH.md`):

```markdown
# Migration Guide: Instance-Level Authorization

## Breaking Change in v0.3.0

API key configuration format has changed to support instance-level permissions.

### Old Format (v0.2.x)

```yaml
api:
  auth_enabled: true
  api_keys:
    - "admin-key-abc123"
    - "user-key-def456"
```

### New Format (v0.3.0+)

**Option A: Maintain Wildcard Access** (Recommended for Single-Tenant)

```yaml
api:
  auth_enabled: true
  api_keys:
    - key: "admin-key-abc123"
      instances: ["*"]  # All instances (default if omitted)
```

**Option B: Instance-Specific Access** (Multi-Tenant)

```yaml
api:
  auth_enabled: true
  api_keys:
    - key: "admin-key-abc123"
      instances: ["*"]
      description: "Full admin access"
    - key: "home-key-def456"
      instances: ["home"]
      description: "Home instance only"
    - key: "cabin-key-ghi789"
      instances: ["cabin"]
      description: "Cabin instance only"
```

### Backward Compatibility

Old string format is still supported:

```yaml
api:
  api_keys:
    - "old-key-123"  # Automatically converted to wildcard access
```

This will be converted internally to:

```yaml
api:
  api_keys:
    - key: "old-key-123"
      instances: ["*"]
```

### Testing Migration

1. Update config file
2. Restart HA Boss
3. Test API access: `curl -H "X-API-Key: your-key" http://localhost:8000/api/status?instance_id=home`
4. Check logs for permission denials

### Troubleshooting

**Error: 403 Forbidden - "API key does not have access to instance"**

Your API key is not authorized for the requested instance. Check:
- Verify `instances` list includes the instance_id you're accessing
- Use `instances: ["*"]` for wildcard access
- Check spelling of instance_id (case-sensitive)
```

---

## Conclusion

**Immediate Action**: Implement **Option 3** (document current behavior) to close this issue.

**Future Action**: Revisit **Option 1** when user demand emerges (3+ requests or MVP graduation).

**Never Implement**: **Option 2** is over-engineering for this project's scope.

This approach follows HA Boss's MVP philosophy: "Start Simple, Learn Over Time."

---

**Next Steps for Issue #144**:
1. ✅ Add security model documentation to README.md
2. ✅ Add multi-tenant deployment guide to docs/DEPLOYMENT.md
3. ✅ Update issue with decision and defer to Phase 4
4. ✅ Close issue as "documented / won't implement for MVP"
