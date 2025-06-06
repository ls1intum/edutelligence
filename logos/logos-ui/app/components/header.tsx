import React, { useContext } from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Image } from 'react-native';
import { ThemeContext } from '../';

export default function Header() {
  const { theme, toggleTheme } = useContext(ThemeContext);

  // Theme-abhängige Styles holen
  const isLight = theme === 'light';

  return (
    <View style={[styles.header, isLight ? styles.lightHeader : styles.darkHeader]}>
      <View style={styles.headerContainer}>
        <Image
          source={require('../../assets/images/logos_full.png')}
          style={styles.header_left}
          resizeMode="contain"
        />
        <Text style={styles.version}>
             0.0.1
        </Text>
      </View>
      <TouchableOpacity
          onPress={toggleTheme}
          style={[styles.button, isLight ? styles.lightButton : styles.darkButton]}
      >
        <Text style={isLight ? styles.lightButtonText : styles.darkButtonText}>
          {isLight ? <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
             className="lucide lucide-moon absolute h-[1.2rem] w-[1.2rem] rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100"
             aria-hidden="true">
          <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"></path>
        </svg> : <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
             className="lucide lucide-sun h-[1.2rem] w-[1.2rem] rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0"
             aria-hidden="true">
          <circle cx="12" cy="12" r="4"></circle>
          <path d="M12 2v2"></path>
          <path d="M12 20v2"></path>
          <path d="m4.93 4.93 1.41 1.41"></path>
          <path d="m17.66 17.66 1.41 1.41"></path>
          <path d="M2 12h2"></path>
          <path d="M20 12h2"></path>
          <path d="m6.34 17.66-1.41 1.41"></path>
          <path d="m19.07 4.93-1.41 1.41"></path>
        </svg>}
        </Text>
      </TouchableOpacity>

    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    width: '100%',
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 12,
  },
  lightHeader: {
    backgroundColor: '#f5f5f5'
  },
  darkHeader: {
    backgroundColor: '#2a2a2a'
  },
  button: {
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 4,
    borderWidth: 1
  },
  lightButton: {
    backgroundColor: '#e0e0e0',
    borderColor: '#cccccc'
  },
  darkButton: {
    backgroundColor: '#3a3a3a',
    borderColor: '#555555'
  },
  lightButtonText: {
    color: '#111111',
    fontSize: 14
  },
  darkButtonText: {
    color: '#f0f0f0',
    fontSize: 14
  },
  header_left: {
    width: 160,
    height: 72
  },
  headerContainer: {
    display: 'flex',
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    color: '#111111',
    fontSize: 14
  },
  version: {
    fontSize: 18, // Erhöhe die Schriftgröße
    color: 'gray', // Setze die Farbe auf grau
  },
});
