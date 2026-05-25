# Mobile Sidebar Overlay Drawer

**Date:** 2026-05-25  
**Branch:** chatV2  
**Status:** Approved

## Problem

On mobile phones and tablets the left panel (`AppSidebar`) is always rendered inline — either 260 px (expanded) or 60 px (icon rail). Both states take up a significant portion of the viewport, making the chat and content area unusable on small screens.

## Goal

Hide the sidebar by default on mobile/tablet (< 768 px). Let the user open it via a hamburger button that slides it in as a full-height overlay, without pushing the main content.

## Scope

**One file changed:** `tutorbot-web/components/ui/AppSidebar.tsx`

No changes to `AppShellContext`, `app-shell-storage.ts`, or `app/(app)/layout.tsx`.

## Design

### Breakpoint

`< 768 px` (Tailwind `md`) — covers phones and most tablets. At `md` and above, the existing inline sidebar behavior is completely unchanged.

### Why no layout changes are needed

When `<aside>` uses `position: fixed`, it is removed from the flex flow. The existing `<main className="flex-1">` in `layout.tsx` already fills all remaining space, so it automatically becomes full-width on mobile with no extra work.

### Local state (added to `AppSidebar`)

| State | Type | Initial value | Notes |
|---|---|---|---|
| `isMobile` | `boolean` | `false` (SSR safe) | Derived from `window.innerWidth < 768`; updated on `resize` |
| `drawerOpen` | `boolean` | `false` | Not persisted to localStorage; always starts closed |

### Mobile rendering (< 768 px)

| Element | Behaviour |
|---|---|
| `<aside>` | `position: fixed`, `top-0 left-0`, `z-40`, `w-[260px]`, `h-screen` |
| Closed state | `translate-x-[-100%]` (off-screen to the left) |
| Open state | `translate-x-0` |
| Animation | `transition-transform duration-200 ease-in-out` |
| Backdrop | `fixed inset-0 bg-black/50 z-30`, rendered only when `drawerOpen`; click closes drawer |
| Hamburger trigger | `fixed top-3 left-3 z-50`, `<Menu>` icon from lucide-react; rendered only when `isMobile && !drawerOpen` |
| Auto-close on navigate | `useEffect` watching `pathname` → `setDrawerOpen(false)` |

The sidebar always renders in full expanded mode when open on mobile (no icon-rail option; the collapse toggle is hidden on mobile).

### Desktop rendering (≥ 768 px)

Zero changes. `sidebarCollapsed` (60 px / 260 px inline sticky) works exactly as before.

## Implementation plan

All changes are in `tutorbot-web/components/ui/AppSidebar.tsx`:

1. Add `isMobile` state — initialise `false`; in a `useEffect`, set from `window.innerWidth < 768` and attach a `resize` listener that updates it.
2. Add `drawerOpen` state — initialise `false`.
3. Auto-close effect — `useEffect([pathname])` → `setDrawerOpen(false)`.
4. Hamburger button — rendered when `isMobile && !drawerOpen`, positioned `fixed top-3 left-3 z-50`.
5. Backdrop — rendered when `isMobile && drawerOpen`, `fixed inset-0 z-30`, `onClick={() => setDrawerOpen(false)}`.
6. `<aside>` class changes — on mobile: `fixed top-0 left-0 z-40 w-[260px] h-screen transition-transform duration-200`, toggling `translate-x-0` / `-translate-x-full`. On desktop: existing `sticky top-0 transition-all duration-200` with `w-[60px]` / `w-[260px]`.
7. Hide the existing collapse toggle button on mobile (it is irrelevant when the drawer is an overlay).

## Out of scope

- Swipe-to-open / swipe-to-close gesture (touch events)
- Scroll-lock on `<body>` when drawer is open
- Remembering drawer state across page loads
