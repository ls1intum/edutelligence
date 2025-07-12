import React, {useContext, useEffect, useState} from 'react';
import {View, Text, StyleSheet, TextInput, Button, ScrollView, Pressable, Modal, TouchableOpacity} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {ThemeContext} from '@/components/theme';
import Footer from '@/components/footer';
import Header from '@/components/header';
import Sidebar from '@/components/sidebar';
import {useRouter} from "expo-router";
import {Picker} from '@react-native-picker/picker';
import {Ionicons} from '@expo/vector-icons';

const privacyOptions = [
    'LOCAL',
    'CLOUD_IN_EU_BY_US_PROVIDER',
    'CLOUD_NOT_IN_EU_BY_US_PROVIDER',
    'CLOUD_IN_EU_BY_EU_PROVIDER'
];

export default function Models() {
    const {theme} = useContext(ThemeContext);
    const [isLoggedIn, setIsLoggedIn] = useState(false);
    const [apiKey, setApiKey] = useState('');
    const router = useRouter();

    const [models, setModels] = useState<any[]>([]);
    const [name, setName] = useState('');
    const [endpoint, setEndpoint] = useState('');
    const [tags, setTags] = useState('');
    const [parallel, setParallel] = useState('1');
    const [privacy, setPrivacy] = useState('LOCAL');
    const [weights, setWeights] = useState({
        latency: '',
        accuracy: '',
        cost: '',
        quality: ''
    });

    const [tooltipText, setTooltipText] = useState('');
    const [tooltipVisible, setTooltipVisible] = useState(false);

    const showTooltip = (text: string) => {
        setTooltipText(text);
        setTooltipVisible(true);
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

    const handleSubmit = async () => {
        const payload = {
            name, endpoint, tags, parallel: parseInt(parallel),
            weight_privacy: privacy,
            weight_latency: 0,
            weight_accuracy: 0,
            weight_cost: 0,
            weight_quality: 0,
            compare_latency: weights.latency,
            compare_accuracy: weights.accuracy,
            compare_cost: weights.cost,
            compare_quality: weights.quality
        };
        try {
            const res = await fetch('/add_provider', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': apiKey
                },
                body: JSON.stringify(payload)
            });
            if (res.ok) {
                loadModels(apiKey);
                setName('');
                setEndpoint('');
                setTags('');
                setParallel('1');
                setPrivacy('LOCAL');
                setWeights({latency: '', accuracy: '', cost: '', quality: ''});
            }
        } catch (e) {
            console.error(e);
        }
    };

    if (!isLoggedIn) return null;

    const Tooltip = ({ text }: { text: string }) => (
        <View style={styles.tooltip}>
            <Text style={styles.tooltipText}>{text}</Text>
        </View>
    );

    return (
        <View style={styles.outer_container}>
            <Header/>
            <View style={[styles.page, theme === 'light' ? styles.light : styles.dark]}>
                <Sidebar/>
                <ScrollView style={styles.content}>
                    <Text style={[styles.title, theme === 'light' ? styles.textLight : styles.textDark]}>
                        Add Provider
                    </Text>
                    <Text style={[theme === 'light' ? styles.textLight : styles.textDark]}>
                        Add a new Provider to Logos
                    </Text>

                    <View style={styles.formRowContainer}>
                        <View style={styles.leftColumn}>
                            {[{
                                label: 'Name', value: name, setter: setName,
                                tooltip: 'Provider Name'
                            }, {
                                label: 'Base-URL', value: endpoint, setter: setEndpoint,
                                tooltip: 'Provider Base-URL'
                            }, {
                                label: 'API-Key', value: tags, setter: setTags,
                                tooltip: 'API-Key from this provider'
                            }].map(({label, value, setter, tooltip, keyboard}) => (
                                <View key={label} style={styles.formRow}>
                                    <Text style={[styles.label, theme === 'light' ? styles.textLight : styles.textDark]}>{label}:
                                        <View onMouseEnter={() => showTooltip(tooltip)} onMouseLeave={() => setTooltipVisible(false)}>
                                            <Ionicons name="help-circle-outline" size={16} style={styles.icon}/>
                                            {tooltipVisible && tooltipText === tooltip && <Tooltip text={tooltip} />}
                                        </View>
                                    </Text>
                                    <TextInput value={value} onChangeText={setter} style={[styles.input, theme === 'light' ? styles.textLight : styles.textDark]}/>
                                </View>
                            ))}
                        </View>

                        <View style={styles.rightColumn}>
                            {[{
                                label: 'Auth-Name', value: name, setter: setName,
                                tooltip: 'Key of the header field used for authentication'
                            }, {
                                label: 'Auth-Format', value: endpoint, setter: setEndpoint,
                                tooltip: 'Value of the header field used for authentication'
                            }].map(({label, value, setter, tooltip, keyboard}) => (
                                <View key={label} style={styles.formRow}>
                                    <Text style={[styles.label, theme === 'light' ? styles.textLight : styles.textDark]}>{label}:
                                        <View onMouseEnter={() => showTooltip(tooltip)} onMouseLeave={() => setTooltipVisible(false)}>
                                            <Ionicons name="help-circle-outline" size={16} style={styles.icon}/>
                                            {tooltipVisible && tooltipText === tooltip && <Tooltip text={tooltip} />}
                                        </View>
                                    </Text>
                                    <TextInput value={value} onChangeText={setter} style={[styles.input, theme === 'light' ? styles.textLight : styles.textDark]}/>
                                </View>
                            ))}
                        </View>
                    </View>
                    <View style={styles.buttons}>
                        <TouchableOpacity style={styles.addButton} onPress={() => router.push('/providers')}>
                            <Text style={styles.addButtonText}>+ Add</Text>
                        </TouchableOpacity>
                        <TouchableOpacity style={styles.abortButton} onPress={() => router.push('/providers')}>
                            <Text style={styles.addButtonText}>- Abort</Text>
                        </TouchableOpacity>
                    </View>
                </ScrollView>
            </View>
            <Footer/>
        </View>
    );
}

const styles = StyleSheet.create({
    page: {flex: 1, flexDirection: 'row'},
    outer_container: {flex: 1},
    content: {flex: 1, padding: 32, width: '100%'},
    title: {fontSize: 28, fontWeight: 'bold', marginBottom: 24, alignSelf: 'center'},
    subheading: {fontSize: 20, fontWeight: '600', marginTop: 40, marginBottom: 16},
    formRowContainer: {flexDirection: 'row', justifyContent: 'space-between', gap: 32, marginBottom: 40},
    leftColumn: {flex: 1},
    rightColumn: {flex: 1},
    formRow: {marginBottom: 20},
    input: {borderWidth: 1, borderColor: '#888', borderRadius: 10, padding: 12},
    label: {fontWeight: 'bold', marginBottom: 6, flexDirection: 'row', alignItems: 'center'},
    modelBox: {padding: 14, backgroundColor: '#4444', borderRadius: 12, marginBottom: 12},
    icon: {marginLeft: 4},
    light: {backgroundColor: '#fff'},
    dark: {backgroundColor: '#1e1e1e'},
    textLight: {color: '#000'},
    textDark: {color: '#fff'},
    buttons: {
      justifyContent: 'flex-end',
      flexDirection: 'row',
    },
    tooltip: {
        position: 'absolute',
        top: 20,
        left: 20,
        backgroundColor: '#333',
        padding: 8,
        borderRadius: 6,
        zIndex: 9999,
        width: "auto",
        maxWidth: 500,
        minWidth: 300,
    },
    tooltipText: {
        color: '#fff',
        fontSize: 12
    },
    addButton: {
        backgroundColor: '#007bff',
        paddingVertical: 12,
        paddingHorizontal: 24,
        borderRadius: 12,
        alignItems: 'center',
        marginVertical: 20,
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.2,
        shadowRadius: 4,
        elevation: 3,
        maxWidth: 300
    },
    abortButton: {
        backgroundColor: '#ff0000',
        paddingVertical: 12,
        paddingHorizontal: 24,
        borderRadius: 12,
        alignItems: 'center',
        marginVertical: 20,
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.2,
        shadowRadius: 4,
        elevation: 3,
        maxWidth: 300
    },
    addButtonText: {
        color: '#fff',
        fontSize: 16,
        fontWeight: '600',
    }
});
