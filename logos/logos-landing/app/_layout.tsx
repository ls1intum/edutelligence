import React, { useEffect, useContext } from 'react';
import { SafeAreaView } from 'react-native-safe-area-context';
import { StatusBar, StyleSheet, View } from 'react-native';
import { Slot } from 'expo-router';
import ThemeProvider, { ThemeContext } from '@/components/theme';

export default function _layout() {
  useEffect(() => {
    console.log('Layout loaded');
  }, []);

  return (
    <ThemeProvider>
      <ThemedLayout />
    </ThemeProvider>
  );
}

function ThemedLayout() {
  const { theme } = useContext(ThemeContext);

  useEffect(() => {
    StatusBar.setBarStyle(theme === 'light' ? 'dark-content' : 'light-content');
  }, [theme]);

  return (
    <SafeAreaView style={[
      styles.safeArea,
      theme === 'light' ? styles.lightBackground : styles.darkBackground
    ]}>
      <View style={styles.container}>
        <Slot />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1
  },
  container: {
    flex: 1
  },
  lightBackground: {
    backgroundColor: '#ffffff'
  },
  darkBackground: {
    backgroundColor: '#1e1e1e'
  }
});