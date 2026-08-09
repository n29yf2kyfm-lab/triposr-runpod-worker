# Going live on eBay

SnapList publishes through eBay's official **Sell Inventory API**. This is what
you need to get a real publish working, in order.

Start in **Sandbox**. It is eBay's full test environment: listings do not go
live, no fees are charged, and you can break things freely. Nothing here costs
money.

---

## 1 · Developer account and keyset

1. Register at **https://developer.ebay.com** and join the eBay Developers
   Program (free).
2. Create an **application keyset** for the **Sandbox** environment. You get
   three values; two of them are ours:

   | eBay calls it | We call it |
   |---|---|
   | App ID (Client ID) | `EBAY_CLIENT_ID` |
   | Cert ID (Client Secret) | `EBAY_CLIENT_SECRET` |
   | Dev ID | not needed |

> **Note for later:** a **production** keyset additionally requires you to stand
> up an HTTPS endpoint that handles eBay's *Marketplace Account Deletion*
> notifications (it validates a challenge token) before the keyset activates.
> Sandbox does not need this. Budget for it before going to production.

## 2 · A Sandbox seller, and a user token

The app lists on **a seller's own account**, so it needs a *user* token — not
just the application keyset.

1. In the developer portal, create a **Sandbox test user** (this is your
   pretend seller).
2. Generate an **OAuth user access token** for that test user with the
   `sell.inventory` scope. The portal has a page for this — it walks you
   through eBay's consent flow and hands back a token.
3. Put it in `EBAY_USER_TOKEN`.

> User tokens **expire** (a couple of hours for the short-lived kind). For a
> real product you store the refresh token and mint access tokens as needed;
> for testing, regenerating by hand is fine. If publishing suddenly returns
> 401, this is why.

## 3 · Business policies — the one that catches everyone

eBay **will not publish** an offer without payment, return and shipping
policies, and it does **not** fall back to sensible defaults.

1. In the **Sandbox** Seller Hub for your test user, opt into **Business
   Policies**.
2. Create one of each: a payment policy, a return policy, a shipping
   (fulfillment) policy.

That is all — SnapList looks up your first policy of each kind automatically.
Only set `EBAY_FULFILLMENT_POLICY_ID` / `EBAY_PAYMENT_POLICY_ID` /
`EBAY_RETURN_POLICY_ID` if you want to pin specific ones.

If they're missing, publishing fails with a message telling you exactly this,
rather than a cryptic eBay error.

## 4 · A category for Sandbox

eBay's category-suggestion API **does not work in Sandbox** — it returns
boilerplate text regardless of what you ask it. So Sandbox needs a category to
fall back on:

```
EBAY_FALLBACK_CATEGORY_ID=112529     # Consumer Electronics > Headphones
```

In production the app resolves the category from the listing title itself, and
this is ignored.

## 5 · Fill in `.env` and publish

```bash
cp .env.example api/.env
# edit api/.env with the values from above
./run.sh
```

The header dots in the app turn **green** as each integration goes live. Walk a
photo through to step 6 and hit **Publish to eBay**.

---

## What the app handles for you

- **Inventory location.** Every offer must reference one; it's created on first
  publish (address comes from `EBAY_LOCATION_*`).
- **Images.** The photo is uploaded to eBay's own image hosting, so you do not
  need to host images publicly. `PUBLIC_BASE_URL` is only a fallback for when
  that upload is unavailable — and note eBay fetches self-hosted images over
  the internet, so it can never see `localhost`.
- **Condition.** Human conditions are mapped to eBay's enum. (eBay has no
  `USED_LIKE_NEW` or `USED_FAIR`, so those become `USED_EXCELLENT` and
  `USED_ACCEPTABLE`.)
- **Listing duration.** Fixed-price offers must be `GTC`; set automatically.

## When publish fails

Failures return eBay's own message, because eBay's errors are specific and
worth reading ("aspect 'Brand' is required for this category" tells you exactly
what to do). The most common causes, in order:

1. **Missing business policies** → step 3 above.
2. **Missing required item specifics** for the category. eBay requires certain
   aspects per category; the app reports which ones are missing.
3. **Expired user token** → regenerate, step 2.
4. **Invalid category** → check `EBAY_FALLBACK_CATEGORY_ID` is a real leaf
   category.

## Moving to production

1. Create a production keyset **and** the account-deletion notification
   endpoint (see step 1's note).
2. Set `EBAY_ENV=production` and swap in production credentials plus a
   production user token for your real seller account.
3. Set up business policies on the real account.
4. Real fees and real buyers apply from here. Test a cheap item first.
