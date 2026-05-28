import React, { useRef, useMemo } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'

const DEFAULT_APERTURE = 8.0
const DEFAULT_PUPIL    = 4.0
const EYEBALL_R        = 12
const MM_SCALE         = 0.8

function Eyelid({ apertureHalf, upper }) {
  const half = Math.max(0.5, apertureHalf * MM_SCALE)
  const sign = upper ? 1 : -1
  const color = upper ? '#d4b896' : '#c4a882'

  const geometry = useMemo(() => {
    const pts = []
    for (let i = 0; i <= 32; i++) {
      const θ = (Math.PI * i) / 32
      pts.push(new THREE.Vector3(
        EYEBALL_R * 0.9 * (Math.cos(θ) - 0.5) * 2,
        sign * (half + 1.5 * Math.sin(θ)),
        EYEBALL_R * 0.97,
      ))
    }
    const curve = new THREE.CatmullRomCurve3(pts)
    return new THREE.TubeGeometry(curve, 32, 0.6, 8, false)
  }, [half, sign])

  return (
    <mesh geometry={geometry}>
      <meshStandardMaterial color={color} roughness={0.6} metalness={0.1} />
    </mesh>
  )
}

function EyeScene({ apertureMm, pupilMm }) {
  const groupRef = useRef()
  useFrame(() => {
    if (groupRef.current) groupRef.current.rotation.y += 0.002
  })

  const ap = apertureMm ?? DEFAULT_APERTURE
  const pd = pupilMm    ?? DEFAULT_PUPIL
  const irisInner = (pd / 2 + 0.5) * MM_SCALE
  const irisOuter = (pd / 2 + 3.0) * MM_SCALE
  const pupilR    = (pd / 2) * MM_SCALE

  return (
    <group ref={groupRef}>
      {/* Eyeball */}
      <mesh>
        <sphereGeometry args={[EYEBALL_R, 48, 32]} />
        <meshStandardMaterial color="#f5ece0" roughness={0.3} metalness={0.05} />
      </mesh>

      {/* Iris ring */}
      <mesh position={[0, 0, EYEBALL_R * 0.98]}>
        <ringGeometry args={[irisInner, irisOuter, 48]} />
        <meshStandardMaterial color="#5b82c4" roughness={0.4} side={THREE.DoubleSide} />
      </mesh>

      {/* Pupil */}
      <mesh position={[0, 0, EYEBALL_R + 0.05]}>
        <circleGeometry args={[pupilR, 32]} />
        <meshStandardMaterial color="#000000" roughness={1} />
      </mesh>

      {/* Corneal reflection */}
      <mesh position={[1.5, 1.5, EYEBALL_R + 0.3]}>
        <circleGeometry args={[0.8, 16]} />
        <meshStandardMaterial color="#ffffff" emissive="#ffffff" emissiveIntensity={0.5} />
      </mesh>

      <Eyelid apertureHalf={ap / 2} upper />
      <Eyelid apertureHalf={ap / 2} upper={false} />
    </group>
  )
}

export default function EyeAnatomy3D({ apertureMm, pupilMm, height = 360 }) {
  return (
    <div style={{
      width: '100%', height,
      borderRadius: 8, overflow: 'hidden',
      background: '#06091a', border: '1px solid rgba(255,255,255,.08)',
    }}>
      <Canvas camera={{ position: [0, 0, 48], fov: 35 }}>
        <ambientLight intensity={0.6} />
        <directionalLight position={[20, 30, 40]} intensity={1.2} />
        <pointLight position={[-10, -10, 20]} intensity={0.4} color="#a0c0ff" />
        <EyeScene apertureMm={apertureMm} pupilMm={pupilMm} />
        <OrbitControls enablePan={false} minDistance={28} maxDistance={80} />
      </Canvas>
    </div>
  )
}
