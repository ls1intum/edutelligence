# Prefix-Based Collection Access Update

## Summary of Changes

Updated the Weaviate RBAC implementation to use **collection prefixes** instead of hard-coded collection lists. This provides a much more scalable and maintainable approach.

## What Changed

### Before: Hard-coded Collection Lists
```python
MICROSERVICE_COLLECTIONS = {
    "atlas": ["Exercise", "Competency", "ClusterCenter"],
    "iris": ["Faqs", "LectureUnits", "BuildLogs", ...],
    "athena": ["Submission", "FeedbackSuggestion"]
}
```

### After: Prefix-based Access
```python
MICROSERVICE_PREFIXES = {
    "atlas": "atlas_",
    "iris": "iris_", 
    "athena": "athena_"
}
```

## Key Benefits

### 1. **Dynamic Collection Creation**
- Services can create new collections without updating RBAC configuration
- No need to modify permissions when adding new collection types
- Automatic access to collections following naming convention

### 2. **Simplified Permissions**
- Wildcard permissions (`atlas_*`, `iris_*`, `athena_*`) cover all collections
- Single permission rule per service instead of per-collection rules
- Cleaner and more maintainable permission structure

### 3. **Clear Ownership**
- Collection names immediately identify the owning service
- Prevents naming conflicts between services
- Easier auditing and troubleshooting

### 4. **Scalability**
- No RBAC updates required when services evolve
- Supports unlimited collections per service
- Future-proof approach

## Updated File Structure

### Core Files Updated:
1. **`permissions.py`** - Now uses wildcard permissions with prefixes
2. **`connection_examples.py`** - Updated to demonstrate prefix-based access
3. **`README.md`** - Documented the new prefix approach
4. **`.env.example`** - Updated for consistency

### Permission Structure:
Each service gets permissions for:
- **Data operations**: `{prefix}*` - Full CRUD access
- **Collection management**: `{prefix}*` - Create/manage collections  
- **Backup operations**: `{prefix}*` - Backup their collections
- **Cluster read**: Health checks and monitoring

## Collection Naming Convention

### Atlas Service
- Prefix: `atlas_`
- Examples: `atlas_exercises`, `atlas_competencies`, `atlas_users`

### Iris Service  
- Prefix: `iris_`
- Examples: `iris_faqs`, `iris_lectures`, `iris_buildlogs`

### Athena Service
- Prefix: `athena_`
- Examples: `athena_submissions`, `athena_feedback`, `athena_reports`

## Migration Path

For existing collections with non-prefixed names:

1. **Option 1: Rename Collections** (Recommended)
   ```python
   # Rename existing collections to follow prefix convention
   old_collection = client.collections.get("Exercise")
   new_collection = client.collections.create("atlas_exercises")
   # Migrate data from old to new collection
   ```

2. **Option 2: Hybrid Approach**
   - Keep existing collections with explicit permissions
   - Use prefixes for new collections
   - Gradually migrate over time

## Security Considerations

- **Prefix enforcement**: Services cannot access collections with other prefixes
- **Wildcard safety**: `*` only matches within the service's prefix scope
- **Clear boundaries**: Each service has a distinct namespace
- **Audit trail**: Collection names reveal ownership and access patterns

This prefix-based approach makes the RBAC system much more maintainable while providing better security through clear service boundaries.
