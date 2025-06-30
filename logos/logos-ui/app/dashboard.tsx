import React, {useContext, useEffect, useState} from 'react';
import {View, Text, StyleSheet, ActivityIndicator} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {ThemeContext} from '@/components/theme';
import Footer from '@/components/footer';
import Header from '@/components/header';
import Sidebar from '@/components/sidebar';
import {useRouter} from "expo-router";

export default function Dashboard() {
    const {theme} = useContext(ThemeContext);
    const [stats, setStats] = useState<{ models: number; requests: number; users: number } | null>(null);
    const [loading, setLoading] = useState(true);
    const [isLoggedIn, setIsLoggedIn] = useState(false);
    const [apiKey, setApiKey] = useState('');
    const router = useRouter();

    useEffect(() => {
        const fetchStats = async () => {
            try {
                const key = await AsyncStorage.getItem('logos_api_key');
                const response = await fetch('https://logos.ase.cit.tum.de:8080/logosdb/generalstats', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'logos_key': key || ''
                    },
                    body: JSON.stringify({
                      logos_key: key
                    })
                });
                const [data, code] = JSON.parse(await response.text());
                console.log(code);
                console.log(data);
                if (code === 200) {
                    setStats({
                        models: data.models,
                        requests: data.requests,
                        users: data.users
                    });
                } else {
                }
            } catch (e) {
                setStats({
                    models: -1,
                    requests: -1,
                    users: -1
                });
                console.error('Error while loading statistics:', e);
            } finally {
                setLoading(false);
            }
        };
        fetchStats();
    }, []);

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
            <Header/>
            <View style={[styles.page, theme === 'light' ? styles.light : styles.dark]}>
                <Sidebar/>
                <View style={styles.content}>
                    <Text style={[styles.title, theme === 'light' ? styles.textLight : styles.textDark]}>
                        Logos-Dashboard
                    </Text>

                    {loading ? (
                        <ActivityIndicator size="large" color="#888" style={{marginTop: 40}}/>
                    ) : stats ? (
                        <View style={styles.statsContainer}>
                            <View style={styles.statBox}>
                                <Text
                                    style={[styles.statNumber, theme === 'light' ? styles.textLight : styles.textDark]}>{stats.models}</Text>
                                <Text
                                    style={[styles.statLabel, theme === 'light' ? styles.textLight : styles.textDark]}>Models</Text>
                            </View>
                            <View style={styles.statBox}>
                                <Text
                                    style={[styles.statNumber, theme === 'light' ? styles.textLight : styles.textDark]}>{stats.requests}</Text>
                                <Text
                                    style={[styles.statLabel, theme === 'light' ? styles.textLight : styles.textDark]}>Requests</Text>
                            </View>
                            <View style={styles.statBox}>
                                <Text
                                    style={[styles.statNumber, theme === 'light' ? styles.textLight : styles.textDark]}>{stats.users}</Text>
                                <Text
                                    style={[styles.statLabel, theme === 'light' ? styles.textLight : styles.textDark]}>User</Text>
                            </View>
                        </View>
                    ) : (
                        <Text style={{marginTop: 20, color: 'red'}}>Error while loading statistics.</Text>
                    )}

                    <View style={styles.dummyCard}>
                        <Text style={theme === 'light' ? styles.textLight : styles.textDark}>
                            Hier erscheinen bald anpassbare Informationsboxen...
                        </Text>
                    </View>
                </View>
            </View>

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