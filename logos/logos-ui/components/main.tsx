import { usePathname, useRouter } from 'expo-router';
import React, { useEffect, useRef, useState } from 'react';
import { Alert } from 'react-native';
import { Image as ExpoImage } from 'expo-image';

import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { Input, InputField } from "@/components/ui/input";
import { Button, ButtonText } from "@/components/ui/button";
import { VStack } from "@/components/ui/vstack";
import { Center } from "@/components/ui/center";
import { useAuth } from '@/components/auth-shell';

type MainProps = {
  /**
   * Route to navigate to after successful login.
   * Pass null to skip navigation (e.g. when rendered inside the auth shell).
   */
  redirectTo?: string | null;
  /**
   * Optional callback to notify consumers about a successful authentication.
   */
  onAuthenticated?: (key: string) => void;
  /**
   * When false, skips the auto-redirect that happens when a stored key is already present.
   * Useful for rendering the login UI inside protected routes without bouncing to /dashboard.
   */
  enableAutoRedirect?: boolean;
};

export default function Main({
  redirectTo = '/dashboard',
  onAuthenticated,
  enableAutoRedirect = true,
}: MainProps = {}) {
  const router = useRouter();
  const pathname = usePathname();
  const { status, apiKey: storedApiKey, setApiKey } = useAuth();
  const [inputKey, setInputKey] = useState('');
  const [isLoggedIn, setIsLoggedIn] = useState(status === 'authenticated');
  const hasNavigatedRef = useRef(false);

  const [hue, setHue] = useState(0);

  const sanitizeKey = (raw: string) =>
    (raw || '').replace(/[\r\n]+/g, '').trim();

  useEffect(() => {
    const interval = setInterval(() => {
      setHue(h => (h + 1) % 360);
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (status === 'unauthenticated') {
      setIsLoggedIn(false);
      hasNavigatedRef.current = false;
    }
  }, [status]);

  useEffect(() => {
    if (!enableAutoRedirect) return;
    if (status !== 'authenticated') return;
    if (pathname !== '/') return;
    if (hasNavigatedRef.current) return;

    const target = redirectTo === null ? null : redirectTo ?? '/dashboard';
    console.info('[Login check] authenticated status, continuing to', target ?? 'current route');
    hasNavigatedRef.current = true;
    setIsLoggedIn(true);
    if (target && target !== pathname) {
      router.replace(target);
    }
    if (storedApiKey.length) {
      onAuthenticated?.(sanitizeKey(storedApiKey));
    }
  }, [status, enableAutoRedirect, redirectTo, pathname, router, storedApiKey, onAuthenticated]);

  const verifyApiKey = async (key: string) => {
    const safeKey = sanitizeKey(key);
    try {
      const response = await fetch("https://logos.ase.cit.tum.de:8080/logosdb/get_role", {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'logos_key': safeKey
        },
        body: JSON.stringify({
          logos_key: safeKey
        })
      });
      let [, code] = JSON.parse(await response.text());
      return code === 200;
    } catch (error) {
      console.error('API-Fehler:', error);
      return false;
    }
  };

  const handleLogin = async () => {
    if (hasNavigatedRef.current) return;
    const cleanedKey = sanitizeKey(inputKey);
    console.info('[Login] verifying entered key…');
    const isValid = await verifyApiKey(cleanedKey);
    if (!isValid) {
      Alert.alert('Login fehlgeschlagen', 'Ungültiger API-Key.');
      return;
    }

    await setApiKey(cleanedKey);
    setIsLoggedIn(true);
    onAuthenticated?.(cleanedKey);
    const target = redirectTo === null ? null : redirectTo ?? '/dashboard';
    console.info('[Login] stored key and navigating to', target ?? 'current route');
    hasNavigatedRef.current = true;
    if (target && target !== pathname) {
      router.replace(target);
    }
  };

  if (status === 'checking') {
    return (
      <Center className="flex-1 bg-white dark:bg-[#1e1e1e]">
        <Text className="text-black dark:text-white">Checking login…</Text>
      </Center>
    );
  }

  if (!isLoggedIn) {
    return (
      <Center className="flex-1 p-6 bg-white dark:bg-[#1e1e1e]">
        <VStack space="xl" className="items-center w-full max-w-[500px]">
          <ExpoImage
            source={require('../assets/images/logos_full.png')}
            style={{ width: 200, height: 90, filter: `hue-rotate(${hue}deg)` } as any}
            contentFit="contain"
          />
          <Text size="2xl" className="font-bold mb-4 text-black dark:text-white text-center">
            Sign in to your account
          </Text>
          
          <Box className="w-1/2 min-w-[300px]">
            <Input className="w-full mb-4 bg-gray-100 dark:bg-[#333] border-outline-300 dark:border-outline-700">
                <InputField 
                    placeholder="Logos API-Key" 
                    value={inputKey}
                    onChangeText={setInputKey}
                    secureTextEntry
                    autoCapitalize="none"
                    onSubmitEditing={handleLogin}
                    className="text-black dark:text-white placeholder:text-gray-500 dark:placeholder:text-gray-400"
                />
            </Input>
          </Box>
          
          <Box className="w-1/2 min-w-[300px]">
             <Button onPress={handleLogin} className="w-full">
                <ButtonText>Login</ButtonText>
             </Button>
          </Box>
        </VStack>
      </Center>
    );
  }
  return (
    <Center className="flex-1">
      <Text className="text-black dark:text-white">
        ✅ Login successful
      </Text>
    </Center>
  );
}
