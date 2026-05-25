# Mobile Sidebar Overlay Drawer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `AppSidebar` auto-hide on mobile/tablet (< 768 px) and open as a slide-in overlay drawer triggered by a fixed hamburger button.

**Architecture:** All changes are in one file — `tutorbot-web/components/ui/AppSidebar.tsx`. Two local state variables (`isMobile`, `drawerOpen`) are added. On mobile the `<aside>` becomes `position: fixed` (removed from flex flow so `<main>` auto-fills full width), and slides in/out via `translate-x`. Desktop behavior is completely unchanged.

**Tech Stack:** Next.js (App Router, pre-release — read `tutorbot-web/node_modules/next/dist/docs/` before writing code), React 19, Tailwind CSS, lucide-react.

---

## File map

| Action | Path | Notes |
|---|---|---|
| Modify | `tutorbot-web/components/ui/AppSidebar.tsx` | Only file changed |

No other files are touched.

---

### Task 1: Add `isMobile` + `drawerOpen` state with resize listener

**Files:**
- Modify: `tutorbot-web/components/ui/AppSidebar.tsx`

Before starting, read the current file so you understand the import list and the `AppSidebar` function body.

- [ ] **Step 1: Add `Menu` to the lucide-react import**

Open `tutorbot-web/components/ui/AppSidebar.tsx`. Find the lucide-react import block (line 6-18). Add `Menu` to the list:

```tsx
import {
  Archive,
  BookOpen,
  Bot,
  ChevronDown,
  ChevronRight,
  LayoutGrid,
  LogOut,
  Menu,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  User,
} from "lucide-react";
```

- [ ] **Step 2: Add the two state variables inside `AppSidebar`**

Inside the `AppSidebar` function, after the existing `const { sidebarCollapsed, setSidebarCollapsed } = useAppShell();` line, add:

```tsx
const [isMobile, setIsMobile] = useState(false);
const [drawerOpen, setDrawerOpen] = useState(false);
```

- [ ] **Step 3: Add the resize effect**

After the two state declarations (still inside `AppSidebar`), add:

```tsx
useEffect(() => {
  const checkMobile = () => setIsMobile(window.innerWidth < 768);
  checkMobile();
  window.addEventListener("resize", checkMobile);
  return () => window.removeEventListener("resize", checkMobile);
}, []);
```

- [ ] **Step 4: Verify the file compiles**

```bash
cd tutorbot-web && npx tsc --noEmit 2>&1 | head -30
```

Expected: no new errors (there may be pre-existing ones — only new errors introduced by this task matter).

- [ ] **Step 5: Commit**

```bash
git add tutorbot-web/components/ui/AppSidebar.tsx
git commit -m "feat(mobile): add isMobile + drawerOpen state to AppSidebar"
```

---

### Task 2: Add auto-close effects

**Files:**
- Modify: `tutorbot-web/components/ui/AppSidebar.tsx`

- [ ] **Step 1: Add auto-close on navigation**

After the resize effect from Task 1, add:

```tsx
useEffect(() => {
  setDrawerOpen(false);
}, [pathname]);
```

This fires whenever the route changes (e.g., user taps a session in the drawer), closing the drawer automatically.

- [ ] **Step 2: Add auto-close when viewport grows past mobile breakpoint**

Immediately after the navigation effect, add:

```tsx
useEffect(() => {
  if (!isMobile) setDrawerOpen(false);
}, [isMobile]);
```

This ensures that if a user resizes from mobile → desktop with the drawer open, the drawer state is cleared.

- [ ] **Step 3: Verify the file compiles**

```bash
cd tutorbot-web && npx tsc --noEmit 2>&1 | head -30
```

Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add tutorbot-web/components/ui/AppSidebar.tsx
git commit -m "feat(mobile): auto-close drawer on navigate and viewport resize"
```

---

### Task 3: Add hamburger trigger button and backdrop

**Files:**
- Modify: `tutorbot-web/components/ui/AppSidebar.tsx`

The `AppSidebar` currently returns a bare `<aside>`. The hamburger button and backdrop must be siblings of `<aside>` (not children), because when the drawer is closed the `<aside>` is off-screen and its children are not clickable.

- [ ] **Step 1: Wrap the return in a fragment**

Find the `return (` statement in `AppSidebar` and wrap the entire `<aside>...</aside>` in a React fragment:

```tsx
return (
  <>
    <aside
      // ... existing props unchanged for now
    >
      {/* ... existing children unchanged */}
    </aside>
  </>
);
```

- [ ] **Step 2: Add the hamburger button before the `<aside>`**

Inside the fragment, before `<aside>`, add:

```tsx
{isMobile && !drawerOpen && (
  <button
    onClick={() => setDrawerOpen(true)}
    className="fixed top-3 left-3 z-50 p-1.5 rounded-md bg-[var(--card)] border border-[var(--border)] text-[var(--foreground)] shadow-sm"
    aria-label={t("Open menu")}
  >
    <Menu className="h-5 w-5" />
  </button>
)}
```

- [ ] **Step 3: Add the backdrop before the `<aside>`**

Still inside the fragment, after the hamburger button and before `<aside>`, add:

```tsx
{isMobile && drawerOpen && (
  <div
    className="fixed inset-0 bg-black/50 z-30"
    onClick={() => setDrawerOpen(false)}
    aria-hidden="true"
  />
)}
```

- [ ] **Step 4: Verify the file compiles**

```bash
cd tutorbot-web && npx tsc --noEmit 2>&1 | head -30
```

Expected: no new errors.

- [ ] **Step 5: Start the dev server and visually verify (desktop)**

```bash
cd tutorbot-web && npm run dev
```

Open `http://localhost:3000` in a browser. At full desktop width the layout should look exactly the same as before — no hamburger button visible, sidebar renders inline.

- [ ] **Step 6: Visually verify (mobile simulation)**

In Chrome DevTools, toggle device toolbar (Ctrl+Shift+M / Cmd+Shift+M) and pick a phone preset (e.g. iPhone 12 — 390px wide). The hamburger button should appear top-left. Because the aside classes have not changed yet the sidebar will still be visible inline — this is expected at this stage.

- [ ] **Step 7: Commit**

```bash
git add tutorbot-web/components/ui/AppSidebar.tsx
git commit -m "feat(mobile): add hamburger trigger and backdrop to AppSidebar"
```

---

### Task 4: Update `<aside>` classes and hide collapse toggle on mobile

**Files:**
- Modify: `tutorbot-web/components/ui/AppSidebar.tsx`

This is the final task — it switches the `<aside>` to `position: fixed` on mobile and wires up the slide animation.

- [ ] **Step 1: Replace the `<aside>` className prop**

Find the current `<aside>` opening tag (it has a `className={cn(...)}` prop). Replace the entire `className` prop with:

```tsx
className={cn(
  "flex flex-col border-r border-[var(--border)] bg-[var(--card)] h-screen",
  isMobile
    ? cn(
        "fixed top-0 left-0 z-40 w-[260px] transition-transform duration-200 ease-in-out",
        drawerOpen ? "translate-x-0" : "-translate-x-full",
      )
    : cn(
        "sticky top-0 transition-all duration-200",
        sidebarCollapsed ? "w-[60px]" : "w-[260px]",
      ),
)}
```

Key points:
- On mobile: `fixed` positioning (removes aside from flex flow so `<main>` fills full width), `z-40` (above content, below backdrop's `z-30`... wait — backdrop is `z-30`, aside is `z-40`, hamburger is `z-50`; the backdrop sits behind the aside, correct).
- On mobile: width is always 260px (always fully expanded when visible).
- On desktop: existing `sticky` + collapsed/expanded width behavior, unchanged.

- [ ] **Step 2: Hide the collapse toggle button on mobile**

Find the collapse toggle button inside the `<aside>` header section. It currently looks like:

```tsx
<button
  onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
  className={cn(
    "p-1 rounded-md hover:bg-[var(--muted)] text-[var(--muted-foreground)]",
    sidebarCollapsed && "mx-auto",
  )}
  aria-label={sidebarCollapsed ? t("Expand sidebar") : t("Collapse sidebar")}
>
  {sidebarCollapsed ? (
    <PanelLeftOpen className="h-4 w-4" />
  ) : (
    <PanelLeftClose className="h-4 w-4" />
  )}
</button>
```

Wrap it in a conditional so it only renders on desktop:

```tsx
{!isMobile && (
  <button
    onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
    className={cn(
      "p-1 rounded-md hover:bg-[var(--muted)] text-[var(--muted-foreground)]",
      sidebarCollapsed && "mx-auto",
    )}
    aria-label={sidebarCollapsed ? t("Expand sidebar") : t("Collapse sidebar")}
  >
    {sidebarCollapsed ? (
      <PanelLeftOpen className="h-4 w-4" />
    ) : (
      <PanelLeftClose className="h-4 w-4" />
    )}
  </button>
)}
```

- [ ] **Step 3: Verify the file compiles**

```bash
cd tutorbot-web && npx tsc --noEmit 2>&1 | head -30
```

Expected: no new errors.

- [ ] **Step 4: Start the dev server**

```bash
cd tutorbot-web && npm run dev
```

- [ ] **Step 5: Verify desktop layout is unchanged**

Open `http://localhost:3000` at full desktop width (> 768px). Check:
- Sidebar renders inline at 260px (expanded) or 60px (collapsed).
- Collapse toggle button is visible and works.
- No hamburger button visible.
- Page layout identical to before.

- [ ] **Step 6: Verify mobile drawer behavior**

In Chrome DevTools, toggle device toolbar and pick a phone preset (e.g. iPhone 12 — 390px). Check:

1. **Initial state:** Sidebar is hidden (off-screen left), main content fills full width, hamburger button visible top-left.
2. **Open drawer:** Tap the hamburger button. Sidebar slides in from the left over the content. A dark backdrop covers the rest of the screen. Collapse toggle is not visible (correct — it's hidden on mobile).
3. **Close via backdrop:** Tap the backdrop. Sidebar slides back off-screen.
4. **Close via navigation:** With drawer open, tap a session link. Sidebar closes automatically after navigation.
5. **Resize to desktop:** With drawer open, resize browser to > 768px. Sidebar switches to inline layout, hamburger disappears.

- [ ] **Step 7: Commit**

```bash
git add tutorbot-web/components/ui/AppSidebar.tsx
git commit -m "feat(mobile): overlay drawer slide animation and hide collapse toggle on mobile"
```

---

## Self-review

**Spec coverage:**
- ✅ Hide sidebar by default on < 768px → Task 4 (aside fixed, `-translate-x-full`)
- ✅ Hamburger trigger → Task 3
- ✅ Backdrop closes drawer → Task 3
- ✅ Slide animation → Task 4 (`transition-transform duration-200 ease-in-out`)
- ✅ Auto-close on navigate → Task 2
- ✅ Desktop unchanged → Task 4 (desktop branch of cn() is verbatim original)
- ✅ No AppShellContext / layout changes → confirmed by file map

**Placeholder scan:** No TBDs, all code blocks complete.

**Type consistency:** `isMobile` / `drawerOpen` / `setDrawerOpen` used consistently across Tasks 1–4. `Menu` icon added in Task 1 and used in Task 3.
