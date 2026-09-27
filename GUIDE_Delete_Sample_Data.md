# Guide: Deleting the Sample Data

At the very first start the administrator chooses **Start with my real data** (empty) or **Try it with sample data
first** (22 break areas with furniture, photos, issues, maintenance, inspections, transactions and 8 months of
satisfaction surveys). If you tried it with sample data, remove it before real use in one of the two ways below.

> **Nothing is lost by mistake.** Every delete is recorded in the **Activity Log** (who, when, from which PC)
> and can be undone from **Settings → Recycle Bin → Restore**.

---

## Option A – Delete everything at once (recommended)

1. Open **Settings** (left menu).
2. In the **Server & Database** box, find **Start real use**.
3. Click **Delete Sample Data** (shown only while sample data is there).
4. Type `DELETE` and press **OK**.

Result: all break areas with their inventory, photos, documents, issues, maintenance, inspections,
surveys and transactions are removed. A backup is created first. The dashboard becomes empty and you can
add your real break areas (**Break Areas → Add New Break Area**).

Kept: your settings (system name, factory, locations, target %) and the item types (Chairs, Tables…).
The sample data is **not** loaded again by itself.

---

## Option B – Delete only some of the sample data

| To delete | Go to | Click |
|---|---|---|
| **A whole break area** (with everything in it) | Open the break area → **Edit** | **Delete Break Area** |
| **An inventory item** (e.g. the TV of one area) | Break area → **Inventory / Contents → Update** → choose the item | **Delete Item** |
| **A photo** | Break area → click the photo | **Delete** |
| **A document** | Break area → **Documents & Reports** | trash icon |
| **An issue** | Break area → **Issues & Maintenance → Follow up** (or **Maintenance** page) | **Delete** |
| **A maintenance job** | Break area → **Issues & Maintenance**, or the **Maintenance** page | trash icon |
| **An inspection** | Break area → **Record Inspection** → list *Previous inspections* | trash icon |
| **A satisfaction result** | Break area → **Satisfaction Survey** box → pencil icon | **Delete** |
| **An item type** (e.g. Refrigerators) | **Furniture & Equipment → Item Types → Edit** | **Delete Item Type** |

Notes:
- An **item type** can only be deleted when no break area has any of it. Delete that item from each
  area's inventory first (or set its quantity to 0).
- **Transactions** (the history of adds/removals) are a record of what happened, so they are removed
  together with their break area, not one by one. Deleting an inventory item adds a transaction line
  “… deleted from the inventory”.

---

## Undo a delete

1. **Settings → Recycle Bin**: every delete is listed with its date, user and what was removed.
2. Click **Restore** next to it. Everything removed in that step comes back.

## Bring the whole sample back

If there are no break areas at all, the Dashboard and Settings show **Load Sample Data** (with a question first).
It is never loaded by itself, and never on top of real data.

## Go back to an earlier moment

**Settings → Backups → Restore** returns ALL data to the time of that backup, for every user.
The current data is saved as a new backup first, so this can be undone too.
