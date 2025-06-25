import { useRouter } from 'expo-router';
import React, {useContext, useEffect, useState} from 'react';
import {
  View,
  Text,
  TextInput,
  Button,
  StyleSheet,
  Alert
} from 'react-native';
import { ThemeContext } from './theme';
import { Image as ExpoImage } from 'expo-image';
import AsyncStorage from '@react-native-async-storage/async-storage';


export default function Main() {
  const router = useRouter();
  const { theme } = useContext(ThemeContext);
  const [apiKey, setApiKey] = useState('');
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  const [hue, setHue] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setHue(h => (h + 1) % 360);
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const checkLogin = async () => {
      const storedKey = await AsyncStorage.getItem('logos_api_key');
      if (storedKey) {
        const valid = await verifyApiKey(storedKey);
        if (valid) {
          setIsLoggedIn(true);
          router.push('/dashboard');
        } else {
          await AsyncStorage.removeItem('logos_api_key');
        }
      }
    };
    checkLogin();
  }, []);

  const verifyApiKey = async (key: string) => {
    try {
      const response = await fetch("https://logos.ase.cit.tum.de:8080/logosdb/get_role", {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'logos_key': key
        },
        body: JSON.stringify({
          logos_key: key
        })
      });
      let [dict, code] = JSON.parse(await response.text());
      console.log(dict);
      return code === 200;
    } catch (error) {
      console.error('API-Fehler:', error);
      return false;
    }
  };

  const handleLogin = async () => {
    const isValid = await verifyApiKey(apiKey);
    if (isValid) {
      await AsyncStorage.setItem('logos_api_key', apiKey);
      setIsLoggedIn(true);
      router.push('/dashboard');
    } else {
      Alert.alert('Login fehlgeschlagen', 'Ungültiger API-Key.');
    }
  };

  if (!isLoggedIn) {
    return (
      <View
        style={[
          styles.container,
          theme === 'light' ? styles.lightBackground : styles.darkBackground
        ]}
      >
        <ExpoImage
          source={require('../assets/images/logos_full.png')}
          style={[styles.logo, { filter: `hue-rotate(${hue}deg)` }]}
          contentFit="contain"
        />
        <Text
          style={[
            styles.title,
            theme === 'light' ? styles.lightText : styles.darkText
          ]}
        >
          Sign in to your account
        </Text>
        <TextInput
          placeholder="Logos API-Key"
          placeholderTextColor={theme === 'light' ? '#888' : '#aaa'}
          value={apiKey}
          onChangeText={setApiKey}
          style={[
            styles.input,
            theme === 'light' ? styles.inputLight : styles.inputDark
          ]}
          secureTextEntry
          autoCapitalize="none"
          onSubmitEditing={handleLogin}
        />
        <View style={styles.buttonContainer}>
          <Button title="Login" onPress={handleLogin} />
        </View>
      </View>
    );
  }
  return (
    <View style={styles.container}>
      <Text style={theme === 'light' ? styles.lightText : styles.darkText}>
        ✅ Login successful
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 24,
    alignItems: 'center',
    justifyContent: 'center'
  },
  title: {
    fontSize: 24,
    marginBottom: 24,
    fontWeight: 'bold'
  },
  input: {
    width: '50%',
    padding: 12,
    marginBottom: 16,
    borderRadius: 8,
    fontSize: 16
  },
  inputLight: {
    backgroundColor: '#f0f0f0',
    color: '#000'
  },
  inputDark: {
    backgroundColor: '#333',
    color: '#fff'
  },
  lightBackground: {
    backgroundColor: '#fff'
  },
  darkBackground: {
    backgroundColor: '#1e1e1e'
  },
  lightText: {
    color: '#000'
  },
  darkText: {
    color: '#fff'
  },
  buttonContainer: {
    width: '50%'
  },
  logo: {
    width: 200,
    height: 90
  }
});
