export type UserRole = "app_developer" | "app_admin" | "logos_admin";

export type MenuItem = {
  label: string;
  path: string;
  aliases?: string[];
  roles: UserRole[];
};

export const ALL_ROLES: UserRole[] = ["app_developer", "app_admin", "logos_admin"];
const ADMIN_AND_ABOVE: UserRole[] = ["app_admin", "logos_admin"];

export const MENU_ITEMS: MenuItem[] = [

  { label: "Dashboard", path: "/dashboard", roles: ["logos_admin"] },
  { label: "Policies", path: "/policies", roles: ["logos_admin"] },
  { label: "Models", path: "/models", aliases: ["/add_model"], roles: ["logos_admin"] },
  { label: "Providers", path: "/providers", aliases: ["/add_provider"], roles: ["logos_admin"] },
  { label: "Statistics", path: "/statistics", roles: ["logos_admin"] },
  { label: "User Management", path: "/user-management", roles: ["logos_admin"] },

  { label: "Billing", path: "/billing", roles: ADMIN_AND_ABOVE },
  { label: "Routing", path: "/routing", roles: ADMIN_AND_ABOVE },
  { label: "API Management", path: "/api-management", roles: ADMIN_AND_ABOVE },

  { label: "Open Code Config", path: "/open-code-config", roles: ALL_ROLES },
  { label: "Rate Limits", path: "/rate-limits", roles: ALL_ROLES },
  { label: "Settings", path: "/settings", roles: ALL_ROLES },
  { label: "Logout", path: "/logout",roles: ALL_ROLES },
];

// Screen role lands on after login or when redirected from forbidden route
export const HOME_ROUTE: Record<UserRole, string> = {
  app_developer: "/open-code-config",
  app_admin:     "/open-code-config",
  logos_admin:   "/dashboard",
};

export function isRouteAllowed(role: UserRole, pathname: string): boolean {
  return MENU_ITEMS
    .filter(item => item.label !== "Logout" && item.roles.includes(role))
    .some(item =>
      pathname === item.path ||
      pathname.startsWith(`${item.path}/`) ||
      item.aliases?.some(a => pathname === a || pathname.startsWith(`${a}/`))
    );
}