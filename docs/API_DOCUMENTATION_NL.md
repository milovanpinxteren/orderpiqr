# OrderPiqR API Documentatie

## Overzicht

OrderPiqR is een magazijnbeheersysteem ontworpen om het pickproces te stroomlijnen. Het systeem biedt een REST API waarmee u producten, orders, pickwachtrijen, apparaten en pickoperaties programmatisch kunt beheren.

### Belangrijkste Functies

- **Multi-tenant architectuur**: Elke klant heeft geïsoleerde data
- **Wachtrijbeheer**: Prioriteer en organiseer pickoperaties
- **Real-time statustracking**: Volg ordervoortgang van concept tot voltooiing
- **Apparaatbeheer**: Registreer en volg pickapparaten
- **Uitgebreide statistieken**: Prestatie-metrics voor orders, producten en apparaten
- **Bulkoperaties**: Importeer orders en werk producten bij in batches
- **Audittrail**: Volledige geschiedenis van alle operaties

## Authenticatie

De API gebruikt JWT (JSON Web Token) authenticatie. Alle API-endpoints (behalve token-endpoints) vereisen authenticatie.

### Token Verkrijgen

```http
POST /api/token/
Content-Type: application/json

{
    "username": "uw_gebruikersnaam",
    "password": "uw_wachtwoord"
}
```

**Antwoord:**
```json
{
    "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

### Token Gebruiken

Voeg het access token toe aan de Authorization header voor alle verzoeken:

```http
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
```

### Token Vernieuwen

Wanneer uw access token verloopt, gebruik het refresh token om een nieuwe te verkrijgen:

```http
POST /api/token/refresh/
Content-Type: application/json

{
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

## API Endpoints

### Interactieve Documentatie

- **Swagger UI**: `/api/docs/` - Interactieve API-documentatie met testmogelijkheden
- **ReDoc**: `/api/redoc/` - Alternatieve documentatieviewer
- **OpenAPI Schema**: `/api/schema/` - Ruwe OpenAPI-specificatie

---

## Producten API

Producten vertegenwoordigen de voorraadartikelen die besteld en gepickt kunnen worden.

### Producten Ophalen

```http
GET /api/products/
```

**Query Parameters:**
- `search` - Filter op productcode of omschrijving
- `active` - Filter op actieve status (`true` of `false`)
- `location` - Filter op locatie (gedeeltelijke match)
- `ordering` - Sorteer resultaten (`code`, `-code`, `location`, `description`)

**Antwoord:**
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

### Product Details Ophalen

```http
GET /api/products/{id}/
```

Retourneert uitgebreide informatie inclusief recente orders.

### Product Aanmaken

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

### Product Opzoeken op Code

```http
GET /api/products/lookup/?code=PROD-001
```

Handig voor barcode scan operaties.

### Product Statistieken Ophalen

```http
GET /api/products/stats/
```

**Antwoord:**
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

### Bulk Product Status Bijwerken

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

Orders vertegenwoordigen klantverzoeken die uit het magazijn moeten worden gepickt.

### Order Status Flow

```
DRAFT → QUEUED → IN_PROGRESS → COMPLETED
   ↓
CANCELLED
```

| Status | Omschrijving |
|--------|--------------|
| `draft` | Beginstatus, nog niet in pickwachtrij |
| `queued` | Wachtend in de pickwachtrij |
| `in_progress` | Wordt momenteel gepickt door een medewerker |
| `completed` | Alle artikelen zijn gepickt |
| `cancelled` | Order is geannuleerd |

### Orders Ophalen

```http
GET /api/orders/
```

**Query Parameters:**
- `search` - Filter op order_code of notities
- `status` - Filter op status (`draft`, `queued`, `in_progress`, `completed`, `cancelled`)
- `created_at__gte` - Orders aangemaakt op of na datum
- `created_at__lte` - Orders aangemaakt op of voor datum
- `in_queue` - Filter op wachtrijstatus (`true` of `false`)
- `ordering` - Sorteer resultaten (`-created_at`, `order_code`, `status`, `queue_position`)

**Antwoord:**
```json
[
    {
        "order_id": 42,
        "customer": 1,
        "order_code": "ORDER-2025-001",
        "created_at": "2025-01-28T10:00:00Z",
        "notes": "Prioriteitsorder",
        "status": "queued",
        "queue_position": 1,
        "completed_at": null,
        "lines": [...],
        "item_count": 7,
        "line_count": 3
    }
]
```

### Order Aanmaken

```http
POST /api/orders/
Content-Type: application/json

{
    "order_code": "ORDER-2025-001",
    "notes": "Prioriteitsorder - voorzichtig behandelen",
    "lines": [
        {"product": 1, "quantity": 2},
        {"product": 2, "quantity": 5}
    ]
}
```

### Order Details Ophalen

```http
GET /api/orders/{id}/
```

Retourneert uitgebreide informatie inclusief productdetails in regels en picklijst info.

### Order Opzoeken op Code

```http
GET /api/orders/lookup/?code=ORDER-2025-001
```

### Order Annuleren

```http
POST /api/orders/{id}/cancel/
```

Alleen concept of wachtrij orders kunnen worden geannuleerd.

### Order Statistieken Ophalen

```http
GET /api/orders/stats/
```

**Antwoord:**
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

### Bulk Orders Aanmaken

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

## Wachtrij API

De Wachtrij API stelt u in staat de pickwachtrij te beheren - orders toevoegen, verwijderen, herschikken en claimen voor picken.

### Wachtrij Ophalen

```http
GET /api/queue/
```

**Antwoord:**
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
            "notes": "Prioriteitsorder",
            "item_count": 5
        }
    ]
}
```

### Wachtrij Statistieken Ophalen

```http
GET /api/queue/stats/
```

**Antwoord:**
```json
{
    "queued_count": 5,
    "in_progress_count": 1,
    "draft_count": 12,
    "completed_today_count": 8,
    "total_items_in_queue": 42
}
```

### Order aan Wachtrij Toevoegen

```http
POST /api/queue/add/{order_id}/
```

### Order uit Wachtrij Verwijderen

```http
POST /api/queue/remove/{order_id}/
```

### Order Claimen voor Picken

```http
POST /api/queue/claim/{order_id}/
Content-Type: application/json

{
    "deviceFingerprint": "abc123def456..."
}
```

### Wachtrij Herschikken

```http
POST /api/queue/reorder/
Content-Type: application/json

{
    "order_ids": [5, 3, 1, 2, 4]
}
```

### Order Verplaatsen in Wachtrij

```http
POST /api/queue/move/{order_id}/up/
POST /api/queue/move/{order_id}/down/
```

---

## Apparaten API

Apparaten vertegenwoordigen fysieke pickapparaten (mobiele telefoons, tablets, scanners) die in het magazijn worden gebruikt.

### Apparaten Ophalen

```http
GET /api/devices/
```

**Query Parameters:**
- `search` - Filter op apparaatnaam of omschrijving
- `user` - Filter op toegewezen gebruiker ID
- `unassigned` - Toon alleen niet-toegewezen apparaten (`true`)
- `ordering` - Sorteer resultaten (`-last_login`, `name`, `-lists_picked`)

**Antwoord:**
```json
[
    {
        "device_id": 1,
        "name": "Magazijn Scanner #1",
        "description": "Hoofdverdieping pickapparaat",
        "device_fingerprint": "abc123...",
        "user": 5,
        "username": "jan.jansen",
        "customer": 1,
        "last_login": "2025-01-28T14:30:00Z",
        "lists_picked": 245,
        "recent_activity": [...]
    }
]
```

### Apparaat Registreren

```http
POST /api/devices/register/
Content-Type: application/json

{
    "device_fingerprint": "abc123def456...",
    "name": "Nieuwe Scanner",
    "description": "Tweede verdieping apparaat"
}
```

Dit endpoint is idempotent - het maakt het apparaat aan als het nieuw is, of werkt de last_login bij als het al bestaat.

### Apparaat Opzoeken op Fingerprint

```http
GET /api/devices/lookup/?fingerprint=abc123...
```

### Apparaat Statistieken Ophalen

```http
GET /api/devices/stats/
```

**Antwoord:**
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

### Apparaat Prestaties Ophalen

```http
GET /api/devices/{id}/performance/
```

**Antwoord:**
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

### Gebruiker Ontkoppelen van Apparaat

```http
POST /api/devices/{id}/unassign_user/
```

---

## Picklijsten API

Een PickList vertegenwoordigt een pickopdracht toegewezen aan een apparaat/medewerker.

### Picklijsten Ophalen

```http
GET /api/picklists/
```

**Query Parameters:**
- `search` - Filter op picklist_code of notities
- `successful` - Filter op successtatus (`true` of `false`)
- `pick_started` - Filter op gestart status
- `device` - Filter op apparaat ID
- `order` - Filter op order ID
- `ordering` - Sorteer resultaten (`-created_at`, `picklist_code`)

### Picklijst Details Ophalen

```http
GET /api/picklists/{id}/
```

Retourneert uitgebreide informatie inclusief alle product picks en order details.

### Picklijst Voltooien

```http
POST /api/picklists/{id}/complete/
Content-Type: application/json

{
    "successful": true,
    "notes": "Alle artikelen succesvol gepickt"
}
```

### Picklijst Statistieken Ophalen

```http
GET /api/picklists/stats/
```

**Antwoord:**
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

Product picks vertegenwoordigen individuele producten binnen een picklijst die gepickt moeten worden.

### Product Picks Ophalen

```http
GET /api/productpicks/
```

**Query Parameters:**
- `search` - Filter op productomschrijving of code
- `picklist` - Filter op picklijst ID
- `product` - Filter op product ID
- `successful` - Filter op successtatus
- `ordering` - Sorteer op `product__location` (standaard, optimaal voor pickvolgorde)

### Pick Markeren als Succesvol

```http
POST /api/productpicks/{id}/success/
Content-Type: application/json

{
    "notes": "Gevonden op alternatieve locatie"
}
```

### Pick Markeren als Mislukt

```http
POST /api/productpicks/{id}/fail/
Content-Type: application/json

{
    "notes": "Niet op voorraad"
}
```

### Bulk Picks Bijwerken

```http
POST /api/productpicks/bulk_update/
Content-Type: application/json

{
    "picks": [
        {"id": 1, "successful": true},
        {"id": 2, "successful": true},
        {"id": 3, "successful": false, "notes": "Niet op voorraad"}
    ]
}
```

### Picks per Picklijst Ophalen

```http
GET /api/productpicks/by-picklist/{picklist_id}/
```

Retourneert picks gesorteerd op productlocatie voor efficiënt picken.

### Product Pick Statistieken Ophalen

```http
GET /api/productpicks/stats/
```

**Antwoord:**
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

## Orderregels API

Orderregels vertegenwoordigen individuele artikelen binnen een order.

### Orderregels Ophalen

```http
GET /api/orderlines/
```

**Query Parameters:**
- `search` - Filter op productomschrijving of code
- `order` - Filter op order ID
- `product` - Filter op product ID
- `quantity__gte` - Filter op minimale hoeveelheid
- `ordering` - Sorteer resultaten (`product__location`, `quantity`)

### Regels per Order Ophalen

```http
GET /api/orderlines/by-order/{order_id}/
```

### Orderregels Samenvatting Ophalen

```http
GET /api/orderlines/summary/
```

**Antwoord:**
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

## Foutafhandeling

De API gebruikt standaard HTTP-statuscodes:

| Statuscode | Omschrijving |
|------------|--------------|
| 200 | Succes |
| 201 | Aangemaakt |
| 207 | Multi-Status (gedeeltelijk succes bij bulkoperaties) |
| 400 | Ongeldig Verzoek - Ongeldige invoer |
| 401 | Niet Geautoriseerd - Ongeldig of ontbrekend token |
| 403 | Verboden - Geen toestemming |
| 404 | Niet Gevonden |
| 405 | Methode Niet Toegestaan |
| 409 | Conflict - Resource al in gebruik |
| 500 | Interne Serverfout |

Foutantwoorden bevatten een detailbericht:

```json
{
    "detail": "Order is not in queue"
}
```

---

## Typische Workflow

1. **Producten Instellen**: Maak producten aan met codes en magazijnlocaties
2. **Order Aanmaken**: Maak een order aan met orderregels die verwijzen naar producten
3. **Aan Wachtrij Toevoegen**: Voeg de order toe aan de pickwachtrij
4. **Apparaat Registreren**: Zorg dat het pickapparaat is geregistreerd
5. **Order Claimen**: Een picker claimt de order uit de wachtrij
6. **Artikelen Picken**: De picker scant en pickt elk artikel, markeert picks als succesvol/mislukt
7. **Picklijst Voltooien**: Markeer de picklijst als voltooid
8. **Order Voltooid**: De order wordt automatisch gemarkeerd als voltooid

### Voorbeeld: Volledige Order Flow

```bash
# 1. Authenticeren
TOKEN=$(curl -s -X POST /api/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "gebruiker", "password": "wachtwoord"}' | jq -r '.access')

# 2. Producten aanmaken
curl -X POST /api/products/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"code": "WIDGET-001", "description": "Blauwe Widget", "location": "A1-01-01"}'

# 3. Order aanmaken
curl -X POST /api/orders/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"order_code": "ORD-001", "lines": [{"product": 1, "quantity": 2}]}'

# 4. Aan wachtrij toevoegen
curl -X POST /api/queue/add/1/ \
  -H "Authorization: Bearer $TOKEN"

# 5. Apparaat registreren
curl -X POST /api/devices/register/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"device_fingerprint": "device-abc-123", "name": "Scanner #1"}'

# 6. Order claimen
curl -X POST /api/queue/claim/1/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"deviceFingerprint": "device-abc-123"}'

# 7. Picks ophalen voor de picklijst
curl /api/productpicks/by-picklist/1/ \
  -H "Authorization: Bearer $TOKEN"

# 8. Picks markeren als succesvol
curl -X POST /api/productpicks/bulk_update/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"picks": [{"id": 1, "successful": true}, {"id": 2, "successful": true}]}'

# 9. Picklijst voltooien
curl -X POST /api/picklists/1/complete/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"successful": true}'
```

---

## Integratie Tips

### Barcode Scannen
Gebruik de lookup endpoints voor snel product/order opzoeken tijdens scannen:
- `GET /api/products/lookup/?code={barcode}`
- `GET /api/orders/lookup/?code={order_code}`

### Efficiënt Picken
Bij het ophalen van picks voor een picklijst worden ze automatisch gesorteerd op productlocatie:
- `GET /api/productpicks/by-picklist/{id}/`

### Monitoring
Gebruik de statistieken endpoints voor dashboards:
- `GET /api/orders/stats/`
- `GET /api/devices/stats/`
- `GET /api/picklists/stats/`
- `GET /api/productpicks/stats/`

### Bulkoperaties
Voor importeren vanuit externe systemen:
- `POST /api/orders/bulk_create/` - Importeer meerdere orders
- `POST /api/products/bulk_update_status/` - Activeer/deactiveer producten

---

## Rate Limiting

Momenteel zijn er geen rate limits ingesteld. Gebruik de API echter verantwoord.

## Ondersteuning

Voor vragen of problemen, neem contact op met uw systeembeheerder.
