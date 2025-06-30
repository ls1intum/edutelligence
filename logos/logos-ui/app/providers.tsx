import React, {useContext, useEffect, useState} from 'react';
import {View, Text, StyleSheet, ActivityIndicator, Pressable, TouchableOpacity} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {ThemeContext} from '@/components/theme';
import Footer from '@/components/footer';
import Header from '@/components/header';
import Sidebar from '@/components/sidebar';
import {useRouter} from "expo-router";
import {compareSource} from "@expo/fingerprint/build/Sort";

export default function Providers() {
    const {theme} = useContext(ThemeContext);
    const [stats, setStats] = useState<{ totalProviders: number; mostUsedProvider: string } | null>(null);
    const [providers, setProviders] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [isLoggedIn, setIsLoggedIn] = useState(false);
    const [apiKey, setApiKey] = useState('');
    const router = useRouter();
    const [showPasswords, setShowPasswords] = useState({});

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
                // Hier Daten laden
                loadProviders();
                loadStats();
            }
        };
        checkLogin();
    }, []);

    const loadProviders = async () => {
        const response = await fetch('https://logos.ase.cit.tum.de:8080/logosdb/get_providers', {
            headers: {
                'Authorization': `Bearer ${apiKey}`,
            },
        });
        const [data, code] = JSON.parse('[[[1,"azure","https://ase-se01.openai.azure.com/openai/deployments/","api-key","{}"]],200]');//await response.text());
        if (code === 200) {
            const formattedProviders = data.map((provider: any[][]) => ({
                id: provider[0],
                name: provider[1],
                baseUrl: provider[2],
                authName: provider[3],
                authFormat: provider[4],
            }));
            setProviders(formattedProviders);
        } else {
        }
        setLoading(false);
    };

    const loadStats = async () => {
        // Implementiere die Logik zum Laden von Statistiken hier
        // Zum Beispiel:
        const response = await fetch('https://logos.ase.cit.tum.de:8080/logosdb/get_general_provider_stats', {
            headers: {
                'Authorization': `Bearer ${apiKey}`,
            },
        });
        const [data, code] = JSON.parse('[{"totalProviders":1},200]');//await response.text());
        if (code === 200 && false) {
            setStats(data);
        } else {
            setStats({"totalProviders": 1, mostUsedProvider: "azure" });
        }
    };

    if (!isLoggedIn) return null;

    return (
        <View style={styles.outer_container}>
            <Header/>
            <View style={[styles.page, theme === 'light' ? styles.light : styles.dark]}>
                <Sidebar/>
                <View style={styles.content}>
                    <Text style={[styles.title, theme === 'light' ? styles.textLight : styles.textDark]}>
                        Providers
                    </Text>
                    <Text style={[styles.subtitle, theme === 'light' ? styles.textLight : styles.textDark]}>
                        Administrate Providers.
                    </Text>
                    <View style={styles.statsContainer}>
                        {stats && (
                            <>
                                <View style={styles.statBox}>
                                    <Text style={[styles.statNumber, theme === 'light' ? styles.textLight : styles.textDark]}>{stats.totalProviders}</Text>
                                    <Text style={[styles.statLabel, theme === 'light' ? styles.textLight : styles.textDark]}>Provider(s)</Text>
                                </View>
                                <View style={styles.statBox}>
                                    <Text style={[styles.statNumber, theme === 'light' ? styles.textLight : styles.textDark]}>{stats.mostUsedProvider}</Text>
                                    <Text style={[styles.statLabel, theme === 'light' ? styles.textLight : styles.textDark]}>Most frequently used Provider</Text>
                                </View>
                            </>
                        )}
                    </View>
                    <TouchableOpacity style={styles.addButton} onPress={() => router.push('/')}>
                        <Text style={styles.addButtonText}>+ Add</Text>
                    </TouchableOpacity>
                    {loading ? (
                        <ActivityIndicator size="large" color="#0000ff"/>
                    ) : (
                        <View style={styles.tableContainer}>
                            <Table providers={providers} showPasswords={showPasswords} setShowPasswords={setShowPasswords} theme={theme}/>
                        </View>
                    )}
                </View>
            </View>
            <Footer/>
        </View>
    );
}

const Table = ({providers, showPasswords, setShowPasswords, theme}) => {
    return (
        <table style={{
            borderCollapse: 'collapse',
            borderRadius: 10,
            overflow: 'hidden',
            boxShadow: '0px 0px 10px rgba(0,0,0,0.1)',
            backgroundColor: theme === 'light' ? '#fff' : '#333',
            color: theme === 'light' ? '#000' : '#fff',
        }}>
            <thead>
                <tr>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>ID</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Name</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Base URL</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Auth Name</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Auth Format</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>API Key</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Modelle</th>
                </tr>
            </thead>
            <tbody>
                {providers.map((provider) => (
                    <tr key={provider.id}>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{provider.id}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{provider.name}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{provider.baseUrl}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{provider.authName}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{provider.authFormat}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{""}</td>
                        <td style={{padding: 10}}>{0}</td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
};

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
    },subtitle: {
        fontSize: 16,
        color: '#666',
        marginBottom: 24,
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
        minWidth: 100,
    },
    statNumber: {
        fontSize: 22,
        fontWeight: 'bold',
    },
    statLabel: {
        marginTop: 4,
        fontSize: 14,
    },
    addButton: {
        backgroundColor: '#007bff',
        padding: 12,
        borderRadius: 8,
        marginBottom: 24,
        alignSelf: 'flex-end',
    },
    addButtonText: {
        color: '#fff',
        fontSize: 18,
    },
    tableContainer: {
        flex: 1,
    },
    table: {
        borderWidth: 1,
        borderColor: '#ddd',
        borderRadius: 8,
        padding: 16,
    },
    tableHeader: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        marginBottom: 12,
    },
    tableHeaderText: {
        fontSize: 18,
        fontWeight: 'bold',
    },
    tableRow: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        paddingVertical: 8,
        borderBottomWidth: 1,
        borderColor: '#ddd',
    },
    tableCell: {
        fontSize: 16,
        borderRightWidth: 1,
        borderRightColor: '#ccc',
    },
    lasttableCell: {
        fontSize: 16,
    },
});