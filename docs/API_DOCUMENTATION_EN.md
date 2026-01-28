# OrderPiqR API Documentation

## Overview

OrderPiqR is a warehouse order management system designed to streamline the picking process. The system provides a REST API that allows you to manage products, orders, picking queues, devices, and track picking operations programmatically.

### Key Features

- **Multi-tenant architecture**: Each customer has isolated data
- **Order queue management**: Prioritize and organize picking operations
- **Real-time status tracking**: Monitor order progress from draft to completion
- **Device management**: Register and track picking devices
- **Comprehensive statistics**: Performance metrics for orders, products, and devices
- **Bulk operations**: Import orders and update products in batch
- **Audit trail**: Complete history of all operations

## Authentication

The API uses JWT (JSON Web Token) authentication. All API endpoints (except token endpoints) require authentication.

### Obtaining a Token

```http
POST /api/token/
Content-Type: application/json

{
    "username": "your_username",
    "password": "your_password"
}
```

**Response:**
```json
{
    "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

### Using the Token

Include the access token in the Authorization header for all requests:

```http
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
```

### Refreshing the Token

When your access token expires, use the refresh token to obtain a new one:

```http
POST /api/token/refresh/
Content-Type: application/json

{
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

## API Endpoints

### Interactive Documentation

- **Swagger UI**: `/api/docs/` - Interactive API documentation with testing capabilities
- **ReDoc**: `/api/redoc/` - Alternative documentation viewer
- **OpenAPI Schema**: `/api/schema/` - Raw OpenAPI specification

---

## Products API

Products represent the inventory items that can be ordered and picked.

### List Products

```http
GET /api/products/
```

**Query Parameters:**
- `search` - Filter by product code or description
- `active` - Filter by active status (`true` or `false`)
- `location` - Filter by location (partial match)
- `ordering` - Sort results (`code`, `-code`, `location`, `description`)

**Response:**
```json
[
    {
        "product_id": 1,
        "code": "PROD-001",
        "description": "Widget A",
        "location": "A1-RIJ01-01",
        "active": true,
        "customer": 1,
        "order_count": 15
    }
]
```

### Get Product Details

```http
GET /api/products/{id}/
```

Returns extended information including recent orders.

### Create Product

```http
POST /api/products/
Content-Type: application/json

{
    "code": "PROD-002",
    "description": "Widget B",
    "location": "A1-RIJ01-02",
    "active": true
}
```

### Lookup Product by Code

```http
GET /api/products/lookup/?code=PROD-001
```

Useful for barcode scanning operations.

### Get Product Statistics

```http
GET /api/products/stats/
```

**Response:**
```json
{
    "total_products": 150,
    "active_products": 142,
    "inactive_products": 8,
    "products_in_orders": 98,
    "locations": [
        {"location": "A1-RIJ01-01", "count": 45},
        {"location": "A2-RIJ02-05", "count": 38}
    ]
}
```

### Bulk Update Product Status

```http
POST /api/products/bulk_update_status/
Content-Type: application/json

{
    "product_ids": [1, 2, 3, 4, 5],
    "active": false
}
```

---

## Orders API

Orders represent customer requests that need to be picked from the warehouse.

### Order Status Flow

```
DRAFT → QUEUED → IN_PROGRESS → COMPLETED
   ↓
CANCELLED
```

| Status | Description |
|--------|-------------|
| `draft` | Initial state, not yet in picking queue |
| `queued` | Waiting in the picking queue |
| `in_progress` | Currently being picked by a worker |
| `completed` | All items have been picked |
| `cancelled` | Order was cancelled |

### List Orders

```http
GET /api/orders/
```

**Query Parameters:**
- `search` - Filter by order_code or notes
- `status` - Filter by status (`draft`, `queued`, `in_progress`, `completed`, `cancelled`)
- `created_at__gte` - Orders created on or after date
- `created_at__lte` - Orders created on or before date
- `in_queue` - Filter by queue status (`true` or `false`)
- `ordering` - Sort results (`-created_at`, `order_code`, `status`, `queue_position`)

**Response:**
```json
[
    {
        "order_id": 42,
        "customer": 1,
        "order_code": "ORDER-2025-001",
        "created_at": "2025-01-28T10:00:00Z",
        "notes": "Priority order",
        "status": "queued",
        "queue_position": 1,
        "completed_at": null,
        "lines": [...],
        "item_count": 7,
        "line_count": 3
    }
]
```

### Create Order

```http
POST /api/orders/
Content-Type: application/json

{
    "order_code": "ORDER-2025-001",
    "notes": "Priority order - handle with care",
    "lines": [
        {"product": 1, "quantity": 2},
        {"product": 2, "quantity": 5}
    ]
}
```

### Get Order Details

```http
GET /api/orders/{id}/
```

Returns extended information including product details in lines and picklist info.

### Lookup Order by Code

```http
GET /api/orders/lookup/?code=ORDER-2025-001
```

### Cancel Order

```http
POST /api/orders/{id}/cancel/
```

Only draft or queued orders can be cancelled.

### Get Order Statistics

```http
GET /api/orders/stats/
```

**Response:**
```json
{
    "total_orders": 250,
    "by_status": {
        "draft": 45,
        "queued": 12,
        "in_progress": 3,
        "completed": 180,
        "cancelled": 10
    },
    "today": {
        "created": 8,
        "completed": 15
    },
    "this_week": {
        "created": 42,
        "completed": 67
    },
    "avg_items_per_order": 4.5
}
```

### Bulk Create Orders

```http
POST /api/orders/bulk_create/
Content-Type: application/json

{
    "orders": [
        {
            "order_code": "ORD-001",
            "notes": "Order 1",
            "lines": [{"product": 1, "quantity": 2}]
        },
        {
            "order_code": "ORD-002",
            "lines": [{"product": 2, "quantity": 3}]
        }
    ]
}
```

---

## Queue API

The Queue API allows you to manage the picking queue - adding orders, removing them, reordering, and claiming orders for picking.

### Get Queue

```http
GET /api/queue/
```

**Response:**
```json
{
    "count": 3,
    "orders": [
        {
            "order_id": 1,
            "order_code": "ORDER-2025-001",
            "status": "queued",
            "queue_position": 1,
            "created_at": "2025-01-28T10:00:00Z",
            "completed_at": null,
            "notes": "Priority order",
            "item_count": 5
        }
    ]
}
```

### Get Queue Statistics

```http
GET /api/queue/stats/
```

**Response:**
```json
{
    "queued_count": 5,
    "in_progress_count": 1,
    "draft_count": 12,
    "completed_today_count": 8,
    "total_items_in_queue": 42
}
```

### Add Order to Queue

```http
POST /api/queue/add/{order_id}/
```

### Remove Order from Queue

```http
POST /api/queue/remove/{order_id}/
```

### Claim Order for Picking

```http
POST /api/queue/claim/{order_id}/
Content-Type: application/json

{
    "deviceFingerprint": "abc123def456..."
}
```

### Reorder Queue

```http
POST /api/queue/reorder/
Content-Type: application/json

{
    "order_ids": [5, 3, 1, 2, 4]
}
```

### Move Order in Queue

```http
POST /api/queue/move/{order_id}/up/
POST /api/queue/move/{order_id}/down/
```

---

## Devices API

Devices represent physical picking devices (mobile phones, tablets, scanners) used in the warehouse.

### List Devices

```http
GET /api/devices/
```

**Query Parameters:**
- `search` - Filter by device name or description
- `user` - Filter by assigned user ID
- `unassigned` - Show only unassigned devices (`true`)
- `ordering` - Sort results (`-last_login`, `name`, `-lists_picked`)

**Response:**
```json
[
    {
        "device_id": 1,
        "name": "Warehouse Scanner #1",
        "description": "Main floor picking device",
        "device_fingerprint": "abc123...",
        "user": 5,
        "username": "john.doe",
        "customer": 1,
        "last_login": "2025-01-28T14:30:00Z",
        "lists_picked": 245,
        "recent_activity": [...]
    }
]
```

### Register Device

```http
POST /api/devices/register/
Content-Type: application/json

{
    "device_fingerprint": "abc123def456...",
    "name": "New Scanner",
    "description": "Second floor device"
}
```

This endpoint is idempotent - it creates the device if new, or updates the last_login if existing.

### Lookup Device by Fingerprint

```http
GET /api/devices/lookup/?fingerprint=abc123...
```

### Get Device Statistics

```http
GET /api/devices/stats/
```

**Response:**
```json
{
    "total_devices": 10,
    "active_today": 5,
    "active_this_week": 8,
    "total_picks": 1500,
    "top_performers": [
        {"device_id": 1, "name": "Scanner #1", "picks": 450, "success_rate": 98.5}
    ]
}
```

### Get Device Performance

```http
GET /api/devices/{id}/performance/
```

**Response:**
```json
{
    "device_id": 1,
    "name": "Scanner #1",
    "total_picklists": 150,
    "successful": 145,
    "failed": 5,
    "success_rate": 96.7,
    "avg_time_per_pick": "00:04:30",
    "picks_today": 12,
    "picks_this_week": 45
}
```

### Unassign User from Device

```http
POST /api/devices/{id}/unassign_user/
```

---

## Pick Lists API

A PickList represents a picking job assigned to a device/worker.

### List Pick Lists

```http
GET /api/picklists/
```

**Query Parameters:**
- `search` - Filter by picklist_code or notes
- `successful` - Filter by success status (`true` or `false`)
- `pick_started` - Filter by started status
- `device` - Filter by device ID
- `order` - Filter by order ID
- `ordering` - Sort results (`-created_at`, `picklist_code`)

### Get Pick List Details

```http
GET /api/picklists/{id}/
```

Returns extended information including all product picks and order details.

### Complete Pick List

```http
POST /api/picklists/{id}/complete/
Content-Type: application/json

{
    "successful": true,
    "notes": "All items picked successfully"
}
```

### Get Pick List Statistics

```http
GET /api/picklists/stats/
```

**Response:**
```json
{
    "total_picklists": 500,
    "completed": 450,
    "successful": 440,
    "failed": 10,
    "in_progress": 5,
    "success_rate": 97.8,
    "avg_time_taken": "00:04:30",
    "today": {
        "completed": 25,
        "successful": 24
    }
}
```

---

## Product Picks API

Product picks represent individual products within a pick list that need to be picked.

### List Product Picks

```http
GET /api/productpicks/
```

**Query Parameters:**
- `search` - Filter by product description or code
- `picklist` - Filter by pick list ID
- `product` - Filter by product ID
- `successful` - Filter by success status
- `ordering` - Sort by `product__location` (default, optimal for picking order)

### Mark Pick as Successful

```http
POST /api/productpicks/{id}/success/
Content-Type: application/json

{
    "notes": "Found in alternate location"
}
```

### Mark Pick as Failed

```http
POST /api/productpicks/{id}/fail/
Content-Type: application/json

{
    "notes": "Out of stock"
}
```

### Bulk Update Picks

```http
POST /api/productpicks/bulk_update/
Content-Type: application/json

{
    "picks": [
        {"id": 1, "successful": true},
        {"id": 2, "successful": true},
        {"id": 3, "successful": false, "notes": "Out of stock"}
    ]
}
```

### Get Picks by Pick List

```http
GET /api/productpicks/by-picklist/{picklist_id}/
```

Returns picks sorted by product location for efficient picking.

### Get Product Pick Statistics

```http
GET /api/productpicks/stats/
```

**Response:**
```json
{
    "total_picks": 1500,
    "successful": 1450,
    "failed": 30,
    "pending": 20,
    "success_rate": 98.0,
    "avg_quantity": 1.2,
    "problem_products": [
        {"product_id": 5, "code": "PROD-005", "description": "Widget E", "failure_count": 8}
    ]
}
```

---

## Order Lines API

Order lines represent individual items within an order.

### List Order Lines

```http
GET /api/orderlines/
```

**Query Parameters:**
- `search` - Filter by product description or code
- `order` - Filter by order ID
- `product` - Filter by product ID
- `quantity__gte` - Filter by minimum quantity
- `ordering` - Sort results (`product__location`, `quantity`)

### Get Lines by Order

```http
GET /api/orderlines/by-order/{order_id}/
```

### Get Order Lines Summary

```http
GET /api/orderlines/summary/
```

**Response:**
```json
{
    "total_lines": 150,
    "total_quantity": 450,
    "unique_products": 85,
    "top_products": [
        {"product_id": 1, "code": "PROD-001", "description": "Widget A", "total_quantity": 25}
    ]
}
```

---

## Error Handling

The API uses standard HTTP status codes:

| Status Code | Description |
|-------------|-------------|
| 200 | Success |
| 201 | Created |
| 207 | Multi-Status (partial success in bulk operations) |
| 400 | Bad Request - Invalid input |
| 401 | Unauthorized - Invalid or missing token |
| 403 | Forbidden - No permission |
| 404 | Not Found |
| 405 | Method Not Allowed |
| 409 | Conflict - Resource already in use |
| 500 | Internal Server Error |

Error responses include a detail message:

```json
{
    "detail": "Order is not in queue"
}
```

---

## Typical Workflow

1. **Setup Products**: Create products with codes and warehouse locations
2. **Create Order**: Create an order with order lines referencing products
3. **Add to Queue**: Add the order to the picking queue
4. **Register Device**: Ensure the picking device is registered
5. **Claim Order**: A picker claims the order from the queue
6. **Pick Items**: The picker scans and picks each item, marking picks as successful/failed
7. **Complete Pick List**: Mark the pick list as complete
8. **Order Completed**: The order is automatically marked as completed

### Example: Complete Order Flow

```bash
# 1. Authenticate
TOKEN=$(curl -s -X POST /api/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "user", "password": "pass"}' | jq -r '.access')

# 2. Create products
curl -X POST /api/products/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"code": "WIDGET-001", "description": "Blue Widget", "location": "A1-01-01"}'

# 3. Create an order
curl -X POST /api/orders/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"order_code": "ORD-001", "lines": [{"product": 1, "quantity": 2}]}'

# 4. Add to queue
curl -X POST /api/queue/add/1/ \
  -H "Authorization: Bearer $TOKEN"

# 5. Register device
curl -X POST /api/devices/register/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"device_fingerprint": "device-abc-123", "name": "Scanner #1"}'

# 6. Claim order
curl -X POST /api/queue/claim/1/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"deviceFingerprint": "device-abc-123"}'

# 7. Get picks for the picklist
curl /api/productpicks/by-picklist/1/ \
  -H "Authorization: Bearer $TOKEN"

# 8. Mark picks as successful
curl -X POST /api/productpicks/bulk_update/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"picks": [{"id": 1, "successful": true}, {"id": 2, "successful": true}]}'

# 9. Complete picklist
curl -X POST /api/picklists/1/complete/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"successful": true}'
```

---

## Integration Tips

### Barcode Scanning
Use the lookup endpoints for quick product/order lookup during scanning:
- `GET /api/products/lookup/?code={barcode}`
- `GET /api/orders/lookup/?code={order_code}`

### Efficient Picking
When fetching picks for a pick list, they're automatically sorted by product location:
- `GET /api/productpicks/by-picklist/{id}/`

### Monitoring
Use the statistics endpoints for dashboards:
- `GET /api/orders/stats/`
- `GET /api/devices/stats/`
- `GET /api/picklists/stats/`
- `GET /api/productpicks/stats/`

### Bulk Operations
For importing from external systems:
- `POST /api/orders/bulk_create/` - Import multiple orders
- `POST /api/products/bulk_update_status/` - Activate/deactivate products

---

## Rate Limiting

Currently, there are no rate limits enforced. However, please use the API responsibly.

## Support

For questions or issues, please contact your system administrator.
