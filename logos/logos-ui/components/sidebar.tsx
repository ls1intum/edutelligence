import React from 'react';
import { ScrollView, Pressable } from 'react-native';
import { useRouter, usePathname } from "expo-router";
import { VStack } from "@/components/ui/vstack";
import { Text } from "@/components/ui/text";
import { Box } from "@/components/ui/box";
import { useAuth } from "./auth-shell";

const menuItems = [
  { label: 'Dashboard', path: '/dashboard' },
  { label: 'Policies', path: '/policies' },
  { label: 'Models', path: '/models', aliases: ['/add_model'] },
  { label: 'Providers', path: '/providers', aliases: ['/add_provider'] },
  { label: 'Billing', path: '/billing' },
  { label: 'Routing', path: '/routing' },
  { label: 'Statistics', path: '/statistics' },
  { label: 'Settings', path: '/settings' },
  { label: 'Logout', path: '/logout' },
] as const;

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { logout } = useAuth();
  console.log('[Sidebar] Rendering');

  const handleLogout = async () => {
    await logout();
    router.push('/');
  };

  const handlePress = (item: typeof menuItems[number]) => {
    if (item.label === 'Logout') {
        handleLogout();
        return;
    }
    router.push(item.path as any);
  };

  const isActive = (item: typeof menuItems[number]) => {
    if (!pathname) return false;
    if (item.label === 'Logout') return false;
    const matchesBase = pathname === item.path || pathname.startsWith(`${item.path}/`);
    const matchesAlias = item.aliases?.some((alias) => pathname === alias || pathname.startsWith(`${alias}/`));
    return matchesBase || Boolean(matchesAlias);
  };

  return (
    <Box className="w-[20%] max-w-[250px] border-r border-outline-200 h-full bg-inherit">
      <ScrollView className="px-6 py-4">
        <VStack space="sm">
          {menuItems.map((item) => {
            const active = isActive(item);
            return (
              <Pressable
                key={item.label}
                onPress={() => handlePress(item)}
                className={`py-3 px-4 rounded-lg border transition-all duration-200 active:opacity-80 active:scale-95
                  ${active
                    ? 'border-2 border-primary-500 bg-primary-50/80 dark:bg-primary-900/30 shadow-soft-2'
                    : 'border-outline-100 bg-transparent hover:bg-background-50'
                  }`}
              >
                <Text
                  className={`text-base font-semibold transition-colors duration-200
                    ${active ? 'text-primary-800 dark:text-primary-100' : 'text-typography-900'}`}
                >
                  {item.label}
                </Text>
              </Pressable>
            );
          })}
        </VStack>
      </ScrollView>
    </Box>
  );
}
