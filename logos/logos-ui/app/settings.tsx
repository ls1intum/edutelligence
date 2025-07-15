import React, {useContext, useEffect, useState} from 'react';
import {View, Text, StyleSheet, ActivityIndicator, ScrollView} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {ThemeContext} from '@/components/theme';
import Footer from '@/components/footer';
import Header from '@/components/header';
import Sidebar from '@/components/sidebar';
import {useRouter} from "expo-router";

export default function Settings() {
    const {theme} = useContext(ThemeContext);
    const [stats, setStats] = useState<{ models: number; requests: number; users: number } | null>(null);
    const [loading, setLoading] = useState(true);
    const [isLoggedIn, setIsLoggedIn] = useState(false);
    const [apiKey, setApiKey] = useState('');
    const router = useRouter();

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
        <View style={styles.outer_container}>
            <ScrollView>
            <Header/>
            <View style={[styles.page, theme === 'light' ? styles.light : styles.dark]}>
                <Sidebar/>
                <View style={styles.content}>
                    <Text style={[styles.title, theme === 'light' ? styles.textLight : styles.textDark]}>
                        Settings
                    </Text>
                    <View style={styles.dummyCard}>
                        <Text style={theme === 'light' ? styles.textLight : styles.textDark}>
                            Hier erscheinen bald Einstellungen...
                        </Text>
                    </View>
                </View>
            </View>
        </ScrollView>
            <Footer/>
        </View>

    );
}

const styles = StyleSheet.create({
    page: {
        flex: 1,
        flexDirection: 'row'
    },
    outer_container: {
        flex: 1
    },
    content: {
        flex: 1,
        padding: 32,
        width: '100%',
    },
    title: {
        fontSize: 28,
        fontWeight: 'bold',
        marginBottom: 24,
        alignSelf: 'center'
    },
    statsContainer: {
        flexDirection: 'row',
        justifyContent: 'center',
        gap: 24,
        marginBottom: 32
    },
    statBox: {
        alignItems: 'center',
        backgroundColor: '#3c3c3c20',
        padding: 16,
        borderRadius: 16,
        minWidth: 100
    },
    statNumber: {
        fontSize: 22,
        fontWeight: 'bold'
    },
    statLabel: {
        marginTop: 4,
        fontSize: 14
    },
    dummyCard: {
        marginTop: 20,
        alignSelf: 'center',
        padding: 20,
        borderRadius: 30,
        borderWidth: 1,
        borderColor: '#aaa'
    },
    light: {
        backgroundColor: '#fff'
    },
    dark: {
        backgroundColor: '#1e1e1e'
    },
    textLight: {
        color: '#000'
    },
    textDark: {
        color: '#fff'
    }
});