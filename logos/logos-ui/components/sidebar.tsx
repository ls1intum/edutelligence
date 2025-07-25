import React, {useContext, useEffect, useState} from 'react';
import {View, Text, StyleSheet, Pressable, ScrollView} from 'react-native';
import { ThemeContext } from './theme';
import {useRouter} from "expo-router";
import AsyncStorage from "@react-native-async-storage/async-storage";

const menuItems = [
  'Dashboard',
  'Policies',
  'Models',
  'Providers',
  'Billing',
  'Routing',
  'Statistics',
  'Settings',
  'Logout'
];

export default function Sidebar() {
  const { theme } = useContext(ThemeContext);
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [apiKey, setApiKey] = useState('');
  const router = useRouter();
  const handleLogout = async () => {
    await AsyncStorage.removeItem('logos_api_key');
    setApiKey('');
    setIsLoggedIn(false);
    router.push('/');
  };

  const handlePress = (item: string) => {
    switch (item) {
        case 'Dashboard':
          router.push('/dashboard');
          break;
        case 'Policies':
          router.push('/policies');
          break;
        case 'Models':
          router.push('/models');
          break;
        case 'Providers':
          router.push('/providers');
          break;
        case 'Billing':
          router.push('/billing');
          break;
        case 'Routing':
          router.push('/routing');
          break;
        case 'Statistics':
          router.push('/statistics');
          break;
        case 'Settings':
          router.push('/settings');
          break;
        case 'Logout':
          handleLogout().then(r => {});
          break;
        default:
          break;
    }
    console.log(`Pressed: ${item}`);
  };

  useEffect(() => {
  const checkLogin = async () => {
    const key = await AsyncStorage.getItem('logos_api_key');
    if (!key) {
      requestAnimationFrame(() => {
        router.replace('/');
      });
    } else {
      setIsLoggedIn(true);
      setApiKey(key);
    }
  };
  checkLogin();
}, []);
  if (!isLoggedIn) return null;


  return (
    <ScrollView style={[styles.sidebar, theme === 'light' ? styles.light : styles.dark]}>
      {menuItems.map((item, index) => (
        <Pressable
          key={index}
          onPress={() => handlePress(item)}
          style={({ pressed }) => [
            styles.menuItem,
            pressed && styles.menuItemPressed,
            theme === 'light' ? styles.menuItemLight : styles.menuItemDark
          ]}
        >
          <Text style={[styles.menuText, theme === 'light' ? styles.menuTextLight : styles.menuTextDark]}>
            {item}
          </Text>
        </Pressable>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  sidebar: {
    width: '20%',
    paddingVertical: 24,
    paddingHorizontal: 16,
    borderRightWidth: 1,
    borderColor: '#ccc',
    height: '100%', // innerhalb von flex-Layout zwischen Header/Footer
    maxWidth: 250,
  },
  menuItem: {
    paddingVertical: 12,
    paddingHorizontal: 14,
    borderRadius: 8,
    marginBottom: 10
  },
  menuItemPressed: {
    opacity: 0.7,
    transform: [{ scale: 0.97 }]
  },
  menuItemLight: {
    backgroundColor: '#e6e6e6'
  },
  menuItemDark: {
    backgroundColor: '#2a2a2a'
  },
  menuText: {
    fontSize: 16,
    fontWeight: '600'
  },
  light: {
  },
  dark: {
    backgroundColor: '#1e1e1e'
  },
  menuTextLight: {
    color: '#222'
  },
  menuTextDark: {
    color: '#fff'
  }
});
