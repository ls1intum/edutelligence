import React, {useContext, useEffect, useState} from 'react';
import {View, Text, StyleSheet, ActivityIndicator, Pressable, TouchableOpacity} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {ThemeContext} from '@/components/theme';
import Footer from '@/components/footer';
import Header from '@/components/header';
import Sidebar from '@/components/sidebar';
import {useRouter} from "expo-router";
import {compareSource} from "@expo/fingerprint/build/Sort";

export default function Models() {
    const {theme} = useContext(ThemeContext);
    const [stats, setStats] = useState<{ totalModels: number; mostUsedModel: string } | null>(null);
    const [models, setModels] = useState<any[]>([]);
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
                // Hier Daten laden
                loadModels();
                loadStats();
            }
        };
        checkLogin();
    }, []);

    const loadModels = async () => {
        try {
            const response = await fetch('https://logos.ase.cit.tum.de:8080/logosdb/get_models', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${apiKey}`,
                    'Content-Type': 'application/json',
                    'logos_key': await AsyncStorage.getItem('logos_api_key'),
                },
                body: JSON.stringify({
                    logos_key: await AsyncStorage.getItem('logos_api_key')
                })
            });
            const [data, code] = JSON.parse(await response.text());
            if (code === 200) {
                const formattedModels = data.map((model: any[][]) => ({
                    id: model[0],
                    name: model[1],
                    endpoint: model[2],
                    api_id: model[3],
                    weight_privacy: model[4],
                    weight_latency: model[5],
                    weight_accuracy: model[6],
                    weight_cost: model[7],
                    weight_quality: model[8],
                    tags: model[9],
                    parallel: model[10],
                    description: model[11],
                }));
                setModels(formattedModels);
            } else {
            }
            setLoading(false);
        } catch (e) {
            setModels([]);
        } finally {
            setLoading(false);
        }

    };

    const loadStats = async () => {
        try {
            const response = await fetch('https://logos.ase.cit.tum.de:8080/logosdb/get_general_model_stats', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${apiKey}`,
                    'Content-Type': 'application/json',
                    'logos_key': await AsyncStorage.getItem('logos_api_key'),
                },
                body: JSON.stringify({
                    logos_key: await AsyncStorage.getItem('logos_api_key')
                })
            });
            const [data, code] = JSON.parse(await response.text());
            if (code === 200 && false) {
                setStats(data);
            } else {
                setStats({totalModels: 0, mostUsedModel: "None" });
            }
        } catch (e) {
            setStats({totalModels: 0, mostUsedModel: "None" });
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
                        Models
                    </Text>
                    <Text style={[styles.subtitle, theme === 'light' ? styles.textLight : styles.textDark]}>
                        Administrate Models.
                    </Text>
                    <View style={styles.statsContainer}>
                        {stats && (
                            <>
                                <View style={styles.statBox}>
                                    <Text style={[styles.statNumber, theme === 'light' ? styles.textLight : styles.textDark]}>{stats.totalModels}</Text>
                                    <Text style={[styles.statLabel, theme === 'light' ? styles.textLight : styles.textDark]}>Models</Text>
                                </View>
                                <View style={styles.statBox}>
                                    <Text style={[styles.statNumber, theme === 'light' ? styles.textLight : styles.textDark]}>{stats.mostUsedModel}</Text>
                                    <Text style={[styles.statLabel, theme === 'light' ? styles.textLight : styles.textDark]}>Most frequently used Model</Text>
                                </View>
                            </>
                        )}
                    </View>
                    <TouchableOpacity style={styles.addButton} onPress={() => router.push('/add_model')}>
                        <Text style={styles.addButtonText}>+ Add</Text>
                    </TouchableOpacity>
                    {loading ? (
                        <ActivityIndicator size="large" color="#0000ff"/>
                    ) : (
                        <View style={styles.tableContainer}>
                            <Table models={models} theme={theme}/>
                        </View>
                    )}
                </View>
            </View>
            <Footer/>
        </View>
    );
}

// @ts-ignore
const Table = ({models, theme}) => {
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
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Endpoint</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>API-ID</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Privacy</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Latency</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Accuracy</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Cost</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Quality</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Tags</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Parallel</th>
                    <th style={{padding: 10, borderBottom: '1px solid #ccc'}}>Description</th>
                </tr>
            </thead>
            <tbody>
                {models.map((model: any) => (
                    <tr key={model.id}>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{model.id}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{model.name}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{model.endpoint}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{model.api_id}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{model.weight_privacy}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{model.weight_latency}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{model.weight_accuracy}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{model.weight_cost}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{model.weight_quality}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{model.tags}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{model.parallel}</td>
                        <td style={{padding: 10, borderRight: '1px solid #ccc'}}>{model.description}</td>
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