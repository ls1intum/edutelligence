// app/index.tsx
import { ThemeContext } from '@/components/theme';
import Header from '@/components/header';
import Main from '@/components/main';
import Footer from '@/components/footer';
import {StatusBar, View} from 'react-native';
import {useContext, useEffect} from "react";

export default function Home() {
  const { theme } = useContext(ThemeContext);
  return (
    <View style={{ flex: 1, backgroundColor: theme === 'light' ? '#ffffff' : '#1e1e1e' }}>
      <Header />
      <Main />
      <Footer />
    </View>
  );
}
