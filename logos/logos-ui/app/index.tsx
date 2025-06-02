import React, { createContext, useEffect, useState } from 'react';
import { StatusBar, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import Footer from './components/footer';
import Header from './components/header';
import Main from './components/main';

// 1. Erstelle den ThemeContext
export const ThemeContext = createContext({
  theme: 'light',
  toggleTheme: () => {}
});

export default function App() {
  const [theme, setTheme] = useState('light');

  // 2. Toggle-Funktion
  const toggleTheme = () => {
    setTheme(prev => (prev === 'light' ? 'dark' : 'light'));
  };

  // 3. Passe den StatusBar-Stil an
  useEffect(() => {
    StatusBar.setBarStyle(theme === 'light' ? 'dark-content' : 'light-content');
  }, [theme]);

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      <SafeAreaView
        style={[
          styles.safeArea,
          theme === 'light' ? styles.lightBackground : styles.darkBackground
        ]}
      >
        <View style={styles.container}>
          <Header />
          <Main />
          <Footer />
        </View>
      </SafeAreaView>
    </ThemeContext.Provider>
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
