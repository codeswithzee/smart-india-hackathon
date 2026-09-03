# Photo feature update

- Seeded/demo products now display real high-resolution Wikimedia Commons photos instead of emoji placeholders.
- Existing rows in `database.db` were backfilled with the same demo photo URLs; all other product/order/user data was left unchanged.
- New/future demo databases receive the photo URLs automatically from `DEMO_IMAGE_MAP`.
- Farmer listings can upload a PNG, JPG, GIF, or WEBP photo up to 10 MB.
- Mobile camera capture is enabled where supported (`capture="environment"`).
- A client-side preview is shown before listing.
- Demo remote image URLs are never deleted when a farmer deletes a product; only local farmer uploads are removed.
- `DEMO_IMAGE_SOURCES.md` contains image source, license, author, and resolution information.

## Important

Google Images itself is not a copyright license. The bundled configuration therefore points to Wikimedia Commons files whose individual pages explicitly state Creative Commons licenses. Check the source/attribution file before commercial redistribution.
